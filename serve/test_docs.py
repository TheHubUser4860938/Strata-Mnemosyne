"""The document index (RAG for the corpus, 2026-10-31): chunk rows in the store, the file on disk.

    python -m unittest serve.test_docs -v

One store, one shape: a folder of text files becomes chunk rows on a DOC/<CORPUS> shelf, in a
scope per corpus, with the spine provenance {file, offset, n, sha256, chunk_sha256} that expands
a hit back into the original passage. The index is INCREMENTAL - the morning pass costs one
stat() sweep, not the whole corpus - keyed by (size, mtime) with sha256 as the authority.
Mock engine, real Postgres (the shared test cluster), no GPU, no embedder: the lexical arm is
the P0 path; the semantic arm rides the same rows the embedder backfills later.
"""
import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path

from serve.frontend import ChatTemplate
from serve.docs import Docs, pack_chunks
from serve.memory import norm_text
from serve.server import MockEngine, Service, serve, ByteTokenizer
from serve.test_memory import MemoryService

try:                                # the suite's own driver (ADR-002): psycopg, same as serve/memory
    import psycopg as _psycopg
    _connect = _psycopg.connect
except ImportError:                 # pragma: no cover - the store needs it anyway
    import psycopg2 as _psycopg2    # type: ignore
    _connect = _psycopg2.connect

ROOT = Path(__file__).resolve().parents[1]


def _federalish(seed: str, paras: int) -> str:
    """Multi-paragraph document text, paragraph k carrying its own rare word."""
    return "\n\n".join(
        f"It is a truth of the {seed} that the {seed}lith {k} governs the extent of the sphere, "
        f"and faction {seed}-{k} arises from the love of gain among men."
        for k in range(paras))


class Chunker(unittest.TestCase):
    """The chunker's contract: bounded rows, no lost words, paragraph-aware boundaries."""

    def test_chunks_stay_within_the_row_ceiling(self):
        text = _federalish("hamil", 400)
        for cap in (200, 1200, 3900):
            for mode in ("paragraphs", "fixed"):
                chunks = pack_chunks(text, cap=cap, mode=mode)
                self.assertTrue(chunks, f"{mode} cap {cap} produced nothing")
                self.assertTrue(all(len(c) <= cap for c in chunks),
                                f"{mode} cap {cap} produced a row over the ceiling")

    def test_every_word_survives_the_split(self):
        text = _federalish("jay", 30)
        for mode in ("paragraphs", "fixed"):
            joined = norm_text(" ".join(pack_chunks(text, cap=1200, mode=mode)))
            self.assertEqual(joined, norm_text(text), f"{mode} lost or duplicated words")

    def test_paragraph_mode_packs_whole_paragraphs_when_they_fit(self):
        text = _federalish("madison", 6)
        chunks = pack_chunks(text, cap=3900, mode="paragraphs")
        self.assertEqual(len(chunks), 1, "six short paragraphs pack into one row")
        paras = text.split("\n\n")
        big = "\n\n".join([_federalish("large", 3)] * 40)      # way over one row
        chunks = pack_chunks(big, cap=3900, mode="paragraphs")
        self.assertTrue(len(chunks) > 1, "the packer must overflow into a second row")
        # the boundary law: a packed row ENDS at a paragraph break, never mid-sentence
        self.assertTrue(chunks[0].endswith("among men."), chunks[0][-40:])

    def test_a_single_huge_paragraph_is_hard_split(self):
        text = "word " * 3000
        chunks = pack_chunks(text, cap=1000, mode="paragraphs")
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))


class DocIndexStore(unittest.TestCase):
    """The index over the store: ledger, rows, incremental rescan, removal - no HTTP."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = MemoryService(self.tmp.name)
        self.docs_dir = Path(self.tmp.name) / "corpus"
        self.docs_dir.mkdir()
        (self.docs_dir / "fed10.txt").write_text(_federalish("faction", 8), encoding="utf-16")
        (self.docs_dir / "fed51.txt").write_text(_federalish("sphere", 8), encoding="utf-8")
        (self.docs_dir / "notes.md").write_text("# A memo\n\nThe memo speaks of malconduct.",
                                                 encoding="utf-8")
        (self.docs_dir / "binary.bin").write_bytes(b"\x00\x01\x02\x03")

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def _rows(self, scope):
        return self.mem.conn.execute(
            "select id, text, source, class, provenance, scope from memories "
            "where scope=%s and invalid_at is null order by id", (scope,)).fetchall()

    def test_index_files_the_corpus_on_one_shelf_with_the_spine(self):
        r = self.mem.docs.index(self.docs_dir, corpus="founding")
        self.assertEqual(r["files"], 3, "txt and md index; the .bin does not")
        self.assertGreater(r["chunks"], 0)
        self.assertEqual(r["skipped"], 0)
        rows = self._rows("doc-founding")
        self.assertEqual(len(rows), r["chunks"], "one row per chunk, and no more")
        for row in rows:
            self.assertTrue(row[2].startswith("doc-index"), row[2])
            self.assertEqual(row[3], "DOC/FOUNDING")
            prov = row[4]
            for key in ("file", "offset", "n", "sha256", "chunk_sha256"):
                self.assertIn(key, prov, f"spine missing {key}")
        ledger = self.mem.docs.list(corpus="founding")
        self.assertEqual({d["path"] for d in ledger},
                         {"fed10.txt", "fed51.txt", "notes.md"})
        self.assertEqual({d["corpus"] for d in ledger}, {"founding"})

    def test_rescan_of_an_unchanged_folder_is_a_stat_sweep(self):
        first = self.mem.docs.index(self.docs_dir, corpus="founding")
        ids_before = {r[0] for r in self._rows("doc-founding")}
        ledger_before = {d["path"]: d["mtime"] for d in self.mem.docs.list(corpus="founding")}
        second = self.mem.docs.index(self.docs_dir, corpus="founding")
        self.assertEqual(second["files"], 0, "nothing moved: the morning pass re-chunks nothing")
        self.assertEqual(second["unchanged"], 3, "the sweep saw all three files and worked on none")
        self.assertEqual({r[0] for r in self._rows("doc-founding")}, ids_before,
                         "an unchanged file keeps its exact rows")
        ledger_after = {d["path"]: d["mtime"] for d in self.mem.docs.list(corpus="founding")}
        self.assertEqual(ledger_after, ledger_before, "the ledger keeps its stamps: no writes")

    def test_one_changed_file_replaces_its_own_chunks_only(self):
        self.mem.docs.index(self.docs_dir, corpus="founding")
        before = {r[4]["file"]: [x for x in self._rows("doc-founding") if x[4]["file"] == r[4]["file"]]
                  for r in self._rows("doc-founding")}
        time.sleep(0.02)                      # mtime resolution is not the detector; sha is
        (self.docs_dir / "fed51.txt").write_text(_federalish("sphere", 60), encoding="utf-8")
        r = self.mem.docs.index(self.docs_dir, corpus="founding")
        self.assertEqual(r["files"], 1, "exactly the touched file re-chunks")
        self.assertEqual(r["unchanged"], 2)
        rows = self._rows("doc-founding")
        fed51 = [x for x in rows if x[4]["file"] == "fed51.txt"]
        self.assertGreater(len(fed51), len(before["fed51.txt"]), "the longer text stored more")
        self.assertEqual(len([x for x in rows if x[4]["file"] == "fed10.txt"]),
                         len(before["fed10.txt"]), "the neighbours kept their rows")
        # the OLD chunk ids are gone (replace, not append): no row keeps a superseded id
        self.assertNotIn(before["fed51.txt"][0][0], {x[0] for x in fed51})

    def test_removal_leaves_the_ledger_empty_and_the_store_quiet(self):
        self.mem.docs.index(self.docs_dir, corpus="founding")
        self.assertTrue(self.mem.docs.remove("founding"))
        self.assertEqual(self._rows("doc-founding"), [])
        self.assertEqual(self.mem.docs.list(corpus="founding"), [])
        self.assertFalse(self.mem.docs.remove("nosuch"), "removing what is not there says so")

    def test_nested_folders_keep_their_relative_path_on_the_spine(self):
        (self.docs_dir / "debates").mkdir()
        (self.docs_dir / "debates" / "conv.txt").write_text(_federalish("convention", 2),
                                                             encoding="utf-8")
        self.mem.docs.index(self.docs_dir, corpus="founding")
        files = {d["path"] for d in self.mem.docs.list(corpus="founding")}
        self.assertIn("debates/conv.txt", files)

    def test_indexed_chunks_are_recallable_by_shelf_and_by_scope(self):
        self.mem.docs.index(self.docs_dir, corpus="founding")
        hits = self.mem.search("sphere lith 7 governs extent", scope="doc-founding", limit=5,
                               semantic=False)
        self.assertTrue(hits, "the lexical arm reaches a chunk of the corpus")
        self.assertIn("sphere", hits[0]["text"])
        shelf = self.mem.search("faction lith 2 arises gain", scope="doc-founding",
                                   classes=["DOC/FOUNDING"], limit=5, semantic=False)
        self.assertTrue(shelf, "the shelf filter reaches the same rows")
        hits = self.mem.search("memo speaks malconduct", scope="doc-founding", limit=3,
                               semantic=False)
        self.assertTrue(hits and "malconduct" in hits[0]["text"])

    def test_explicit_corpus_names_the_scope_and_the_shelf(self):
        self.mem.docs.index(self.docs_dir, corpus="debate", klass="DOC/CONV",
                            scope="convention")
        rows = self._rows("convention")
        self.assertTrue(rows)
        self.assertEqual({r[3] for r in rows}, {"DOC/CONV"})

    def test_fixed_mode_is_the_control_chunker(self):
        r = self.mem.docs.index(self.docs_dir, corpus="founding", mode="fixed", cap=1500)
        self.assertGreater(r["chunks"], 0)
        rows = self._rows("doc-founding")
        self.assertTrue(all(len(x[1]) <= 1500 for x in rows))


class AttachingStore(unittest.TestCase):
    """The tools' lane (m8_docs against a RUNNING server): a minimal duck-type - attach()'d
    connection, no caches, the store's own _dt boundary - driving the same Docs pipeline.
    Reproduction of the 2026-10-31 first-run failure: the adapter returned epoch floats where
    the store converts to aware datetimes, and the row insert died on DatatypeMismatch."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import m8_docs
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = MemoryService(self.tmp.name)          # creates the schema in the shared cluster
        self.conn = _connect(self.svc._pg_uri, dbname=self.svc._dbname)
        self.store = m8_docs._AttachingStore(self.conn, None)
        self.store.docs = Docs(self.store)

    def tearDown(self):
        self.conn.close()
        self.svc.close()
        self.tmp.cleanup()

    def test_the_attaching_lane_indexes_and_rereads(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "one.txt").write_text(_federalish("helvidius", 3), encoding="utf-8")
            r = self.store.docs.index(d, corpus="duck")
            self.assertEqual(r["files"], 1)
            self.assertGreater(r["chunks"], 0)
            rows = self.conn.execute(
                "select text, class, provenance from memories where scope=%s",
                ("doc-duck",)).fetchall()
            self.assertEqual(len(rows), r["chunks"])
            self.assertEqual(rows[0][1], "DOC/DUCK")
            self.assertIn("offset", rows[0][2])
            self.assertEqual([f["path"] for f in self.store.docs.list("duck")], ["one.txt"])


class DocsOverHttp(unittest.TestCase):
    """The op=docs wire: the server is the only place the folder is known, so every app
    inherits the index through it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.docs_dir = Path(cls.tmp.name) / "kb"
        cls.docs_dir.mkdir()
        (cls.docs_dir / "a.txt").write_text(_federalish("helvidius", 4), encoding="utf-8")
        tok = ByteTokenizer()
        cls.svc = Service(MockEngine(tok, "the mock answer", max_context=131072), tok,
                          ChatTemplate(ROOT / "serve/chat_template.jinja"))
        cls.svc.memory = MemoryService(cls.tmp.name)
        cls.httpd = serve(cls.svc, port=0)
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.svc.memory.close()
        cls.tmp.cleanup()

    def _post(self, req):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", "/memory", json.dumps(req), {"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode())

    def test_index_then_list_round_trip(self):
        status, r = self._post({"op": "docs", "action": "index",
                                "folder": str(self.docs_dir), "corpus": "helvidius"})
        self.assertEqual(status, 200)
        self.assertTrue(r["ok"])
        self.assertEqual(r["docs"]["indexed"]["files"], 1)
        status, r = self._post({"op": "docs", "action": "list", "corpus": "helvidius"})
        self.assertEqual([d["path"] for d in r["docs"]["files"]], ["a.txt"])

    def test_a_missing_folder_is_a_400_that_says_what_to_do(self):
        status, r = self._post({"op": "docs", "action": "index", "corpus": "x"})
        self.assertEqual(status, 400)
        self.assertIn("folder", r["error"]["message"])

    def test_the_menu_names_docs(self):
        status, r = self._post({"op": "nonsense"})
        self.assertEqual(status, 400)
        self.assertIn("docs", r["error"]["message"])


if __name__ == "__main__":
    unittest.main()
