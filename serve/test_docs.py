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

    def test_a_word_longer_than_the_cap_is_cut_not_left_whole(self):
        """Audit 2026-10-31: a word over `cap` used to ride alone, so pack_chunks returned a row
        over the ceiling and remember() raised mid-pass (a base64 blob or a long URL is enough)."""
        blob = "x" * 4500
        for mode in ("paragraphs", "fixed"):
            chunks = pack_chunks(f"start {blob} end", cap=1000, mode=mode)
            self.assertTrue(all(len(c) <= 1000 for c in chunks), f"{mode}: row over the ceiling")
            self.assertEqual("".join(chunks).replace(" ", ""), "start" + blob + "end",
                             f"{mode}: the split lost or duplicated characters")


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

    def test_replace_folds_the_retired_rows_out_of_the_token_table(self):
        """Audit F1: the per-file replace must tell the store's cached token table WHICH rows
        died (retired=), not just that the stamp moved - else the server ranks against a
        phantom corpus of deleted chunks until its next rebuild."""
        self.mem.docs.index(self.docs_dir, corpus="founding")
        seen: list = []
        real = self.mem._dedupe_amend
        self.mem._dedupe_amend = lambda *a, **kw: (seen.append(kw.get("retired") or ()),
                                                   real(*a, **kw))[1]
        try:
            (self.docs_dir / "fed51.txt").write_text(_federalish("sphere", 40), encoding="utf-8")
            self.mem.docs.index(self.docs_dir, corpus="founding")
        finally:
            self.mem._dedupe_amend = real
        folded = [i for fold in seen for i in fold]
        self.assertTrue(folded, "the replace passed retired ids to the token-table fold")

    def test_a_tilde_folder_is_a_path_not_a_literal_directory_name(self):
        """Audit F2: an app sends "~/kb"; index() must expanduser it."""
        import os
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / "kb").mkdir()
            (Path(home) / "kb" / "one.txt").write_text(_federalish("tilde", 2), encoding="utf-8")
            old = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                r = self.mem.docs.index("~/kb", corpus="tilde")
            finally:
                if old is not None:
                    os.environ["HOME"] = old
            self.assertEqual(r["files"], 1)

    def test_exts_as_a_comma_string_is_not_iterated_as_characters(self):
        """Audit F4: ".txt,.md" arriving as a STRING used to split into letters, and
        endswith(('.', 't', ...)) matches half the folder."""
        (self.docs_dir / "extra.json").write_text('{"a": 1}', encoding="utf-8")
        r = self.mem.docs.index(self.docs_dir, corpus="founding", exts=".txt,.md")
        self.assertEqual(r["files"], 3)
        files = {d["path"] for d in self.mem.docs.list(corpus="founding")}
        self.assertNotIn("extra.json", files)

    def test_every_statement_the_index_runs_holds_the_store_lock(self):
        """Audit 2026-10-31: the class's own law is 'every statement runs under svc.lock', and
        the stat-gate SELECT read the ledger outside it. The doc tests are single-threaded, so
        this is the check that makes the law visible: v0.2.9 added parallel slots, and one
        connection shared by two writers is exactly where that reads wrong."""
        real, outside = self.mem.conn, []
        owned = self.mem.lock._is_owned        # RLock: does THIS thread hold it right now?

        class LockGuard:
            def __init__(self, conn):
                self._c = conn

            def execute(self, *a, **k):
                if not owned():
                    outside.append(str(a[0]).splitlines()[0][:48])
                return self._c.execute(*a, **k)

            def __getattr__(self, name):       # commit, cursor, rollback: the real connection's
                return getattr(self._c, name)

        self.mem.conn = LockGuard(real)
        try:
            self.mem.docs.index(self.docs_dir, corpus="founding")
        finally:
            self.mem.conn = real
        self.assertEqual(outside, [], "statements ran on the store connection outside svc.lock")

    def test_a_cap_above_the_row_ceiling_is_clamped_not_stored_over(self):
        """Audit 2026-10-31: --cap and the wire's "cap" reached remember() unclamped, and the
        store refuses any row over 4,000 characters - so a generous cap killed the pass."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "big.txt").write_text("faction " * 1500, encoding="utf-8")   # ~12,000 chars
            r = self.mem.docs.index(d, corpus="clamped", cap=9000)
            self.assertEqual(r["files"], 1)
            rows = self._rows("doc-clamped")
            self.assertGreater(len(rows), 1, "the clamp splits the paragraph")
            self.assertTrue(all(len(x[1]) <= 4000 for x in rows), max(len(x[1]) for x in rows))

    def test_a_human_corpus_name_gets_a_legal_shelf_and_a_legal_scope(self):
        """Audit 2026-10-31: the old weld produced DOC/THE-FEDERALIST-PAPERS-1788, which CLASS_RE
        refuses (no hyphen), and scope_name() answered the illegal name with 'default' - so a
        corpus with a space filed its chunks in the user's own project scope."""
        r = self.mem.docs.index(self.docs_dir, corpus="the federalist papers.1788")
        self.assertEqual(r["class"], "DOC/THE.FEDERALIST.PAPERS.1788")
        self.assertEqual(r["scope"], "doc-the-federalist-papers.1788")
        self.assertTrue(self._rows(r["scope"]))
        self.assertEqual(self._rows("default"), [], "nothing leaked into the user's default scope")

    def test_an_illegal_explicit_scope_is_refused_rather_than_silently_defaulted(self):
        with self.assertRaises(ValueError):
            self.mem.docs.index(self.docs_dir, corpus="founding", scope="not a scope")
        self.assertEqual(self._rows("default"), [])

    def test_a_corpus_keeps_its_ledger_scope_and_refuses_a_silent_move(self):
        """Audit F5, now guarded: the per-file replace only knows the CURRENT scope, so a changed
        scope used to leave the old scope's rows standing beside the new ones."""
        first = self.mem.docs.index(self.docs_dir, corpus="founding", scope="convention")
        self.assertEqual(first["scope"], "convention")
        again = self.mem.docs.index(self.docs_dir, corpus="founding")     # names no scope
        self.assertEqual(again["scope"], "convention", "a re-index adopts the ledger's home")
        before = len(self._rows("convention"))
        with self.assertRaises(ValueError) as cm:
            self.mem.docs.index(self.docs_dir, corpus="founding", scope="assembly")
        self.assertIn("convention", str(cm.exception))
        self.assertEqual(len(self._rows("convention")), before, "the refusal changed nothing")
        self.assertEqual(self._rows("assembly"), [])

    def test_identical_passages_in_two_files_keep_their_own_rows(self):
        """Audit 2026-10-31: remember()'s exact-text dedup ran over the whole scope, so the second
        file's chunk folded into the FIRST file's row and its provenance (file, offset) was lost."""
        with tempfile.TemporaryDirectory() as d:
            text = _federalish("twin", 3)
            (Path(d) / "a.txt").write_text(text, encoding="utf-8")
            (Path(d) / "b.txt").write_text(text, encoding="utf-8")
            r = self.mem.docs.index(d, corpus="twins")
            self.assertEqual(r["chunks"], 2, "one row per chunk per file")
            rows = self._rows("doc-twins")
            self.assertEqual(len(rows), 2, "no chunk folded into its twin in the other file")
            self.assertEqual({x[4]["file"] for x in rows}, {"a.txt", "b.txt"})

    def test_prune_folds_the_retired_rows_out_of_the_token_table(self):
        """Audit 2026-10-31: the prune deleted without RETURNING id and amended with nothing
        retired, so the cached df weights kept counting rows that were gone."""
        self.mem.docs.index(self.docs_dir, corpus="founding")
        (self.docs_dir / "notes.md").unlink()
        seen: list = []
        real = self.mem._dedupe_amend
        self.mem._dedupe_amend = lambda *a, **kw: (seen.append(kw.get("retired") or ()),
                                                   real(*a, **kw))[1]
        try:
            r = self.mem.docs.index(self.docs_dir, corpus="founding")
        finally:
            self.mem._dedupe_amend = real
        self.assertEqual(r["removed"], 1)
        self.assertTrue([i for fold in seen for i in fold],
                        "the prune passed the retired ids to the token-table fold")

    def test_prune_retires_rows_the_ledger_never_learned(self):
        """A pass killed between its chunk writes and its ledger upsert leaves rows no ledger-only
        prune can see: the live founding pass left 66 of them for one Hume volume."""
        self.mem.docs.index(self.docs_dir, corpus="founding")
        self.mem.remember("an orphan chunk of a file the ledger never heard of", scope="doc-founding",
                          provenance={"file": "influencers/ghost.txt", "corpus": "founding",
                                      "offset": 0, "n": 0})
        self.assertTrue(any(x[4]["file"] == "influencers/ghost.txt" for x in self._rows("doc-founding")))
        self.mem.docs.index(self.docs_dir, corpus="founding")
        self.assertFalse(any(x[4]["file"] == "influencers/ghost.txt" for x in self._rows("doc-founding")),
                         "the orphan row is retired with the corpus, not left standing")

    def test_the_ledger_restamps_a_scope_left_empty_by_an_older_row(self):
        """A ledger row written before the scope column carried a value (every store that
        indexed with the first build) comes back into the one-scope law: a pass that knows the
        corpus's home fills the blanks in, so corpora() and list() never show a blank scope."""
        self.mem.docs.index(self.docs_dir, corpus="founding")
        with self.mem.lock:
            self.mem.conn.execute("update docs set scope='' where corpus='founding'")
            self.mem.conn.commit()
        time.sleep(0.02)
        (self.docs_dir / "fed51.txt").write_text(_federalish("sphere", 20), encoding="utf-8")
        r = self.mem.docs.index(self.docs_dir, corpus="founding")
        self.assertEqual(r["files"], 1)
        self.assertEqual({d["scope"] for d in self.mem.docs.list(corpus="founding")},
                         {"doc-founding"})

    def test_the_spine_offset_points_at_its_own_chunk_in_the_collapsed_file(self):
        """The offset is what expands a hit back into the passage - and what the routing eval
        scores against - so it has to be the chunk's real position in the whitespace-collapsed
        file. The old running sum of len(chunk)+1 drifted the moment a word was cut across two
        rows (the pieces join with no space) and at every packed paragraph boundary."""
        (self.docs_dir / "blob.txt").write_text("y" * 9000 + "\n\n" + _federalish("offset", 6),
                                                 encoding="utf-8")
        self.mem.docs.index(self.docs_dir, corpus="founding")
        rows = self._rows("doc-founding")
        self.assertGreater(len(rows), 4)
        by_file = {}
        for r in rows:
            by_file.setdefault(r[4]["file"], []).append(r)
        for name, group in by_file.items():
            body = " ".join(Docs._read(self.docs_dir / name).split())   # the reader the index uses
            for r in group:
                chunk, off = r[1], r[4]["offset"]
                self.assertEqual(body[off:off + len(chunk)], chunk,
                                 f"{name} chunk {r[4]['n']}: offset {off} misses its own text")

    def test_remove_retires_the_corpus_not_the_whole_scope(self):
        """Two corpora may share a scope (an explicit --scope); the old scope-wide delete would
        have taken the other corpus's rows with it."""
        self.mem.docs.index(self.docs_dir, corpus="founding", scope="shared")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "other.txt").write_text(_federalish("other", 2), encoding="utf-8")
            self.mem.docs.index(d, corpus="others", scope="shared")
            self.assertTrue(self.mem.docs.remove("founding"))
        left = self._rows("shared")
        self.assertTrue(left, "the neighbour corpus keeps its rows")
        self.assertEqual({x[4]["corpus"] for x in left}, {"others"})


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

    def _get(self, qs):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", "/memory?" + qs, headers={"Accept": "application/json"})
        return json.loads(conn.getresponse().read().decode())

    def test_get_docs_one_answers_the_corpora_tally(self):
        """Audit F3: the web page and every operator see WHAT the store can route over.
        stats.docs is a plain list of per-corpus tallies (own corpus: tests share the class)."""
        status, r = self._post({"op": "docs", "action": "index",
                                "folder": str(self.docs_dir), "corpus": "garrison"})
        self.assertEqual(status, 200)
        card = self._get("docs=1")
        self.assertEqual([c["corpus"] for c in card["stats"]["docs"]], ["garrison"])
        self.assertGreater(card["stats"]["docs"][0]["chunks"], 0)

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

    def test_wire_exts_as_a_string_is_not_split_into_characters(self):
        """Audit 2026-10-31: the handler wrapped exts in tuple(str(x) for x in ...), so a comma
        STRING became single characters and the store's own normalization never saw the value.
        (Named to sort last: the class shares one store, and the tally test above is exact.)"""
        (self.docs_dir / "sidecar.json").write_text('{"a": 1}', encoding="utf-8")
        status, r = self._post({"op": "docs", "action": "index", "folder": str(self.docs_dir),
                                "corpus": "wire", "exts": ".txt,.md", "cap": 9000})
        self.assertEqual(status, 200, r)
        self.assertEqual(r["docs"]["indexed"]["files"], 1, "the .json sidecar is not a text file")
        files = self._post({"op": "docs", "action": "list", "corpus": "wire"})[1]["docs"]["files"]
        self.assertEqual([d["path"] for d in files], ["a.txt"])


if __name__ == "__main__":
    unittest.main()
