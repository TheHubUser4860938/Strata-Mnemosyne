"""serve/docs.py - the document index: RAG for the corpus, in the store the engine already runs.

The 2026-10-30 ruling stands: the corpus path is TEXT + ROUTING. The file stays the territory;
the store keeps the map. This module turns a folder of text files into CHUNK ROWS -
`memories` rows on a shelf family (DOC/<CORPUS>), in a scope per corpus, source 'doc-index' -
each carrying the SPINE provenance {file, offset, n, sha256, chunk_sha256} that expands a hit
back into the original passage (the gap RESEARCH.md item 7 named: sentences with provenance,
no document object). Retrieval needs no new machinery: the chunk rows ride the store's lexical
arm (GIN -> BM25) and, once the embedder has walked them, the fused arm - the same RRF the
facts use.

The index is INCREMENTAL, which is the whole answer to the community complaint ("the whole
corpus gets re-indexed from scratch every morning, 10-15 minutes"). A rescan stats every file
against the `docs` ledger and re-chunks ONLY the files whose (size, mtime) moved; mtime is the
cheap gate, sha256 the authority (a touch that rewrites identical bytes re-chunks one file -
honest, not silent). An unchanged folder costs one stat() sweep.

Chunking is a choice, not a constant (arXiv 2603.06976: content-aware beat fixed-length,
nDCG@5 0.459 against <0.244; Vectara NAACL 2025 found fixed can win): the default packs whole
paragraphs to the row ceiling; mode='fixed' is the control, the ~4,000-char windows the
routing bench measured. Both feed the same rows; the eval sweeps both.

Scope-per-corpus (not one mega-scope) is deliberate: remember()'s exact-text dedup scan runs
over the writing scope, so a folder-sized scope keeps every write at the measured flat
~27 ms/row on 3,900-char chunks. The embed pass rides inside remember() (embed-then-lock),
so a 30k-chunk corpus indexes in the measured ~13 min lexical / ~3.4 h with the embedder on.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

from .memory import class_name, scope_name

DEFAULT_EXTS = (".txt", ".md")
CHUNK_CAP = 3900          # remember()'s 4,000-char ceiling minus the whitespace-collapse slack
PARA_RE = re.compile(r"\n\s*\n+")

# The ledger's DDL, byte-identical to the entry in serve/memory.py's _PG_DDL. The store creates
# it at startup; an ATTACHING tool (m8_docs against a running server) creates it on first use,
# so a store that predates the table - every store, until its server's next boot - answers
# without a migration step. IF NOT EXISTS makes the two owners idempotent against each other.
_DOCS_DDL = """create table if not exists docs(
     corpus text not null,
     path text not null,
     scope text not null default '',
     size bigint not null default 0,
     mtime bigint not null default 0,
     sha256 text not null default '',
     chunks integer not null default 0,
     indexed_at timestamptz,
     primary key (corpus, path))"""


def pack_chunks(text: str, cap: int = CHUNK_CAP, mode: str = "paragraphs") -> list[str]:
    """Split a document into rows of at most `cap` characters (whitespace-collapsed as stored).

    'paragraphs': pack whole blank-line-separated paragraphs while they fit, so a row ENDS at a
    paragraph boundary - a hard split only when one paragraph cannot fit alone.
    'fixed': the control windower, ~`cap` characters cut at word boundaries.
    In both modes every word of the source survives exactly once, in order."""
    if cap < 32:
        raise ValueError(f"chunk cap must be >= 32 (got {cap})")
    if mode not in ("paragraphs", "fixed"):
        raise ValueError(f"mode: one of \"paragraphs\", \"fixed\" (got {mode!r})")
    units = [p for p in PARA_RE.split(text) if p.strip()] if mode == "paragraphs" \
        else _words_to_units(text, cap)
    out: list[str] = []
    for unit in units:
        if mode == "fixed":
            for piece in _hard_split(unit, cap):
                out.append(" ".join(piece.split()))
            continue
        unit = unit.strip()
        if len(unit) <= cap:
            if out and len(out[-1]) + 2 + len(unit) <= cap:
                out[-1] = out[-1] + "\n\n" + unit      # pack the paragraph into the open row
                continue
            out.append(unit)
        else:
            for piece in _hard_split(unit, cap):
                piece = " ".join(piece.split())
                if out and len(out[-1]) + 2 + len(piece) <= cap and not out[-1].endswith("\n\n"):
                    out[-1] = out[-1] + "\n\n" + piece
                else:
                    out.append(piece)
    return [c for c in ( " ".join(c.split()) for c in out) if c]


def _words_to_units(text: str, cap: int) -> list[str]:
    """Fixed windows cut at word boundaries, so joining the rows back reproduces the text."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = min(i + cap, n)
        if j < n:
            k = text.rfind(" ", i + 1, j + 1)
            if k > i:
                j = k
        out.append(text[i:j])
        i = j + (1 if j < n and text[j] == " " else 0)
    return out


def _hard_split(unit: str, cap: int) -> list[str]:
    """Cut at word boundaries so the rows are whole words; a word longer than cap rides alone."""
    pieces, cur = [], ""
    for word in unit.split():
        if cur and len(cur) + 1 + len(word) > cap:
            pieces.append(cur)
            cur = word
        else:
            cur = cur + " " + word if cur else word
    if cur:
        pieces.append(cur)
    return pieces


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _corpus_class(corpus: str) -> str:
    """DOC/<CORPUS>: upper-case, spaces weld to hyphens, and the call-number grammar's other
    separators (/, .) become hyphens too - 'the federalist papers.1788' -> DOC/THE-FEDERALIST-
    PAPERS-1788, one address, not a shelf tree the owner never chose."""
    return class_name("DOC/" + re.sub(r"[/ .]+", "-", corpus))


class Docs:
    """The folder->rows pipeline, hung off a MemoryService (svc.docs). Thread-safe by the
    store's own law: every statement runs under svc.lock on the store's connection; the file
    reads and the embed calls happen OUTSIDE the lock, the same division remember() uses."""

    def __init__(self, svc):
        self.svc = svc

    def _ensure(self):
        """The ledger exists before any verb reads it - the attacher's path (a running server
        booted on the old DDL list), and a fresh store's first docs call before its own
        startup ran. One IF NOT EXISTS, idempotent against the store's own _startup."""
        with self.svc.lock:
            self.svc.conn.execute(_DOCS_DDL)
            self.svc.conn.commit()

    def index(self, folder, corpus: str, *, klass: str | None = None, scope: str | None = None,
              cap: int = CHUNK_CAP, mode: str = "paragraphs", exts=DEFAULT_EXTS,
              guard: bool = False) -> dict:
        """Index `folder` into rows under `corpus`. Returns the honest tally:
        {files, chunks, skipped, unchanged, removed, seconds, scope, class, corpus}.
        files/chunks/skipped count the WORK this pass did; unchanged counts stat-swept files
        that needed none; removed counts ledger files that left the folder."""
        t0 = time.time()
        self._ensure()
        corpus = str(corpus or "").strip()
        if not corpus:
            raise ValueError("index needs a corpus name to shelve and scope the rows under")
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"folder not found: {root} - name a directory of "
                             f"{'/'.join(exts)} files")
        klass = _corpus_class(corpus) if klass is None else class_name(klass)
        scope = scope_name(scope or f"doc-{corpus}")[:40]
        source = f"doc-index-{time.strftime('%Y-%m-%d')}"   # <= 40 chars, the column's ceiling
        seen, n_files, n_chunks, n_skip, n_unchanged = set(), 0, 0, 0, 0
        for dirpath, _dirs, names in os.walk(root):
            for name in sorted(names):
                if not name.lower().endswith(tuple(exts)):
                    continue
                p = Path(dirpath) / name
                rel = p.relative_to(root).as_posix()
                seen.add(rel)
                st = p.stat()
                row = self.svc.conn.execute(
                    "select size, mtime, sha256 from docs where corpus=%s and path=%s",
                    (corpus, rel)).fetchone()
                digest = None
                if row is not None and int(row[0]) == st.st_size and int(row[1]) == int(st.st_mtime):
                    n_unchanged += 1
                    continue                            # the morning pass: stat, keep, move on
                digest = _sha256(p)                     # the authority: cheap gate moved -> hash
                if row is not None and row[2] == digest:
                    with self.svc.lock:                 # touched, not changed: the stamp rides
                        self.svc.conn.execute(
                            "update docs set mtime=%s where corpus=%s and path=%s",
                            (int(st.st_mtime), corpus, rel))
                        self.svc.conn.commit()
                    n_unchanged += 1
                    continue
                text = self._read(p)
                chunks = pack_chunks(text, cap=cap, mode=mode)
                doc_sha = digest if digest is not None else _sha256(p)
                with self.svc.lock:                     # replace, never append: the file's own
                    self.svc.conn.execute(              # rows retire together
                        "delete from memories where scope=%s and provenance->>'file'=%s"
                        " and provenance->>'corpus'=%s", (scope, rel, corpus))
                    self.svc.conn.commit()
                    self.svc._touched(reason="doc-replace")
                    self.svc._dedupe_amend()            # the deleted rows fold out; an
                    self.svc._vdirty = True             # unpredicted stamp moves the rebuild
                off = 0
                for i, chunk in enumerate(chunks):
                    self.svc.remember(chunk, scope=scope, source=source, guard=guard, klass=klass,
                                      provenance={"file": rel, "corpus": corpus, "offset": off,
                                                  "n": i, "sha256": doc_sha,
                                                  "chunk_sha256": hashlib.sha256(
                                                      chunk.encode("utf-8")).hexdigest()})
                    off += len(chunk) + 1               # the joiner's char in the concatenated body
                with self.svc.lock:
                    self.svc.conn.execute(
                        "insert into docs(path, corpus, scope, size, mtime, sha256, chunks,"
                        " indexed_at) values(%s,%s,%s,%s,%s,%s,%s,%s)"
                        " on conflict (corpus, path) do update set size=excluded.size,"
                        " mtime=excluded.mtime, sha256=excluded.sha256, chunks=excluded.chunks,"
                        " indexed_at=excluded.indexed_at",
                        (rel, corpus, scope, st.st_size, int(st.st_mtime), doc_sha, len(chunks),
                         self.svc._dt(time.time())))
                    self.svc.conn.commit()
                n_files += 1
                n_chunks += len(chunks)
                n_skip += sum(1 for c in chunks if len(c) >= cap)   # a full row = a split paragraph
        removed = self._prune(corpus, seen)
        return {"files": n_files, "chunks": n_chunks, "skipped": n_skip,
                "unchanged": n_unchanged, "removed": removed,
                "seconds": round(time.time() - t0, 3), "scope": scope, "class": klass,
                "corpus": corpus}

    def list(self, corpus: str | None = None) -> list[dict]:
        """The ledger: one row per indexed file. Without a corpus, every corpus's files."""
        self._ensure()
        q = ("select path, corpus, size, mtime, sha256, chunks, indexed_at from docs"
             + (" where corpus=%s" if corpus else "") + " order by corpus, path")
        with self.svc.lock:
            rows = self.svc.conn.execute(q, (corpus,) if corpus else ()).fetchall()
        return [{"path": r[0], "corpus": r[1], "size": r[2], "mtime": r[3], "sha256": r[4],
                 "chunks": r[5], "indexed_at": str(r[6])} for r in rows]

    def _scope_of(self, corpus: str) -> str:
        """Where the corpus's rows ACTUALLY live: the ledger's stored scope (an explicit scope
        at index time is kept there), with the doc-<corpus> default as the fallback for a
        corpus indexed before the column existed."""
        with self.svc.lock:
            row = self.svc.conn.execute(
                "select scope from docs where corpus=%s limit 1", (corpus,)).fetchone()
        return (row and row[0]) or scope_name(f"doc-{corpus}")[:40]

    def corpora(self) -> list[dict]:
        """Per-corpus tallies - the map a reader uses to know what the store can route over."""
        self._ensure()
        with self.svc.lock:
            rows = self.svc.conn.execute(
                "select corpus, count(*), sum(chunks), max(indexed_at) from docs"
                " group by corpus order by corpus").fetchall()
        return [{"corpus": r[0], "files": r[1], "chunks": r[2], "indexed_at": str(r[3])}
                for r in rows]

    def remove(self, corpus: str) -> bool:
        """Retire a corpus: its chunk rows go, its ledger goes. The FILES on disk are the
        territory and stay untouched (the text-plus-routing law: rows are the map)."""
        led = self.list(corpus)
        if not led:
            return False
        scope = self._scope_of(corpus)
        with self.svc.lock:
            self.svc.conn.execute("delete from memories where scope=%s", (scope,))
            self.svc.conn.execute("delete from docs where corpus=%s", (corpus,))
            self.svc.conn.commit()
            self.svc._touched(reason="doc-remove")
            self.svc._dedupe_amend()
            self.svc._vdirty = True
        return True

    def _prune(self, corpus: str, seen: set) -> int:
        """Files that left the folder since the last pass: their ledger rows and their chunk
        rows go together (a map entry with no territory behind it is a lie)."""
        with self.svc.lock:
            stale = self.svc.conn.execute(
                "select path from docs where corpus=%s", (corpus,)).fetchall()
            gone = [r[0] for r in stale if r[0] not in seen]
            if gone:
                scope = self._scope_of(corpus)
                self.svc.conn.execute(
                    "delete from memories where scope=%s and provenance->>'corpus'=%s"
                    " and provenance->>'file' = any(%s)",
                    (scope, corpus, gone))
                self.svc.conn.execute("delete from docs where corpus=%s and path = any(%s)",
                                      (corpus, gone))
                self.svc.conn.commit()
                self.svc._touched(reason="doc-prune")
                self.svc._dedupe_amend()
                self.svc._vdirty = True
        return len(gone)

    @staticmethod
    def _read(p: Path) -> str:
        for enc in ("utf-8", "utf-16", "latin-1"):       # the corpus is a library, not a schema
            try:
                return p.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return p.read_text(encoding="utf-8", errors="replace")
