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

Scope-per-corpus (not one mega-scope) is deliberate: a corpus is one address on the shelf and one
recall scope. The chunk writes ride remember() with exact=False - one row per chunk even when two
files carry the same passage, and no scope-wide text scan per write (that scan is what made the
22k-row founding pass take hours). The embed pass still rides inside remember() (embed-then-lock),
so the embedder is the long pole when it is on.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

from .memory import CLASS_MAX, class_name, scope_name

DEFAULT_EXTS = (".txt", ".md")
CHUNK_CAP = 3900          # remember()'s 4,000-char ceiling minus the whitespace-collapse slack
ROW_MAX = 4000            # remember()'s hard ceiling; Docs.index clamps a larger --cap here
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
    In both modes every character of the source survives exactly once, in order (a word longer
    than `cap` is cut, because remember() refuses a row over its own ceiling)."""
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
    """Cut at word boundaries so the rows are whole words; a word longer than cap is cut into
    cap-sized pieces. The old version let that word ride alone, which produced a row over the
    row ceiling and made remember() raise mid-pass (a base64 blob or a long URL was enough).
    Every character still survives exactly once, in order."""
    pieces, cur = [], ""
    for word in unit.split():
        while len(word) > cap:                 # no word boundary can save this one: cut it
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(word[:cap])
            word = word[cap:]
        if not word:
            continue
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


def _mtime_us(st) -> int:
    """The gate's clock: MICROSECOND mtime in a bigint. Second resolution (the first build's
    int(st_mtime)) made a rewrite inside the same second look unchanged - a suite-load lottery
    on the replace tests, and a real one-second blind spot in production. Old rows hold
    second-stamps; the first rescan after the change re-hashes them once, the sha arm absorbs
    the work, and the ledger restamps in us. Self-healing, no migration."""
    return int(st.st_mtime * 1_000_000)


def _corpus_class(corpus: str) -> str:
    """DOC/<CORPUS>: upper-case, and every run the call-number grammar cannot hold becomes a DOT -
    the one legal separator that keeps the name one address, not a shelf tree:
    'the federalist papers.1788' -> DOC/THE.FEDERALIST.PAPERS.1788. CLASS_RE has no hyphen (a
    hyphenated address is refused on purpose, see class_list), so the previous version's hyphen
    weld could never pass class_name: a corpus with a space failed to index at all."""
    slug = re.sub(r"[^A-Z0-9]+", ".", str(corpus).upper()).strip(".")
    if not slug:
        raise ValueError(f"corpus {corpus!r} has no letters or digits to shelve it under")
    try:
        return class_name("DOC/" + slug)
    except ValueError as e:
        raise ValueError(f"corpus {corpus!r} makes a shelf longer than {CLASS_MAX} characters; "
                         "pass a shorter --class") from e


def _scope_for(corpus: str) -> str:
    """The default scope for a corpus: 'doc-<corpus>' with every run SCOPE_RE cannot hold welded
    to a hyphen (40 chars max, starts with a letter or digit, A-Z a-z 0-9 . _ - only).

    The old form handed 'doc-the federalist papers' to scope_name(), whose fallback is
    'default' - so a human corpus name silently filed its rows in the user's default project
    scope, where a chunk could exact-dedup against a real fact (and remove() would then have
    deleted that whole scope). A docs scope fails closed now; it never borrows 'default'."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(corpus)).strip("._-")
    if not slug:
        raise ValueError(f"corpus {corpus!r} has no letters or digits to name a scope")
    return ("doc-" + slug)[:40].rstrip("._-") or "doc"


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
        that needed none; removed counts ledger files that left the folder.
        ONE SCOPE PER CORPUS: a re-index that names no scope adopts the ledger's stored scope;
        naming a different one is refused (remove the corpus first), because the per-file
        replace only knows the current scope and a silent move would leave the old scope's rows
        standing beside the new ones (the audit's F5 edge, now guarded rather than annotated)."""
        t0 = time.time()
        self._ensure()
        corpus = str(corpus or "").strip()
        if not corpus:
            raise ValueError("index needs a corpus name to shelve and scope the rows under")
        # exts arrives as a list (the tool), a comma string (an app hand-writing the JSON), or a
        # list of comma strings; a bare string iterated as-is splits into CHARACTERS, and endswith
        # on single letters matches half the folder (audit F4, 2026-10-31). One normalization.
        if isinstance(exts, str):
            exts = [exts]
        parts: list[str] = []
        for x in (exts if exts is not None else DEFAULT_EXTS):
            parts.extend(str(x).split(","))
        exts = tuple("." + x.strip().lower().lstrip(".") for x in parts if x.strip())
        root = Path(str(folder)).expanduser()       # "~/docs" from an app is a path, not a dir name
        if not root.is_dir():
            raise ValueError(f"folder not found: {root} - name a directory of "
                             f"{'/'.join(exts)} files")
        klass = _corpus_class(corpus) if klass is None else class_name(klass)
        requested, scope = scope, None
        if requested is None:
            scope = _scope_for(corpus)
        else:
            scope = scope_name(requested, fallback="")   # never the 'default' fallback: fail closed
            if not scope:
                raise ValueError("scope must be 1-40 characters of A-Z a-z 0-9 . _ - and start "
                                 "with a letter or digit")
        with self.svc.lock:                         # the ledger's home for this corpus, if any
            homes = sorted({r[0] for r in self.svc.conn.execute(
                "select distinct scope from docs where corpus=%s", (corpus,)).fetchall() if r[0]})
        if homes and scope not in homes:
            if requested is None and len(homes) == 1:
                scope = homes[0]                    # a plain re-index keeps the corpus where it lives
            else:
                raise ValueError(f"corpus {corpus!r} is already indexed under scope {homes[0]!r}; "
                                 f"one scope per corpus - remove it first to move it to {scope!r}")
        cap = min(int(cap), ROW_MAX)                # remember() refuses a row over its ceiling
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
                with self.svc.lock:                 # every statement on this connection, by law
                    row = self.svc.conn.execute(
                        "select size, mtime, sha256 from docs where corpus=%s and path=%s",
                        (corpus, rel)).fetchone()
                digest = None
                if row is not None and int(row[0]) == st.st_size and int(row[1]) == _mtime_us(st):
                    n_unchanged += 1
                    continue                            # the morning pass: stat, keep, move on
                digest = _sha256(p)                     # the authority: cheap gate moved -> hash
                if row is not None and row[2] == digest:
                    with self.svc.lock:                 # touched, not changed: the stamp rides
                        self.svc.conn.execute(
                            "update docs set mtime=%s where corpus=%s and path=%s",
                            (_mtime_us(st), corpus, rel))
                        self.svc.conn.commit()
                    n_unchanged += 1
                    continue
                text = self._read(p)
                chunks = pack_chunks(text, cap=cap, mode=mode)
                doc_sha = digest if digest is not None else _sha256(p)
                with self.svc.lock:                     # replace, never append: the file's own
                    gone = [r[0] for r in self.svc.conn.execute(   # rows retire together, and the
                        "delete from memories where scope=%s and provenance->>'file'=%s"
                        " and provenance->>'corpus'=%s returning id",
                        (scope, rel, corpus)).fetchall()]          # store's token table folds them
                    self.svc.conn.commit()
                    self.svc._touched(reason="doc-replace")
                    self.svc._dedupe_amend(retired=gone)  # the deleted rows fold out; an
                    self.svc._vdirty = True             # unpredicted stamp moves the rebuild
                collapsed = " ".join(text.split())   # the body the spine's offsets count in -
                cur = 0                              # the eval harness collapses the same way
                for i, chunk in enumerate(chunks):
                    pos = collapsed.find(chunk, cur)  # anchor it: a cut long word joins with no
                    off = pos if pos >= 0 else cur    # space and a packed paragraph with one, so
                    self.svc.remember(chunk, scope=scope, source=source, guard=guard, exact=False,
                                      klass=klass,
                                      provenance={"file": rel, "corpus": corpus, "offset": off,
                                                  "n": i, "sha256": doc_sha,
                                                  "chunk_sha256": hashlib.sha256(
                                                      chunk.encode("utf-8")).hexdigest()})
                    cur = off + len(chunk)            # the next row starts here (a cut word) or
                                                      # one char later (the space between rows)
                with self.svc.lock:
                    self.svc.conn.execute(
                        "insert into docs(path, corpus, scope, size, mtime, sha256, chunks,"
                        " indexed_at) values(%s,%s,%s,%s,%s,%s,%s,%s)"
                        " on conflict (corpus, path) do update set size=excluded.size,"
                        " mtime=excluded.mtime, sha256=excluded.sha256, chunks=excluded.chunks,"
                        " scope=excluded.scope, indexed_at=excluded.indexed_at",
                        # scope=excluded.scope is belt-and-braces, not the load-bearing part: the
                        # guard above means a stored scope cannot drift, and the blank-fill after
                        # the walk repairs the rows the first build left empty (so the upsert arm
                        # has no test of its own - say so rather than imply one)
                        (rel, corpus, scope, st.st_size, _mtime_us(st), doc_sha, len(chunks),
                         self.svc._dt(time.time())))
                    self.svc.conn.commit()
                n_files += 1
                n_chunks += len(chunks)
                n_skip += sum(1 for c in chunks if len(c) >= cap)   # a full row = a split paragraph
        removed = self._prune(corpus, seen)
        with self.svc.lock:                         # legacy ledger rows carried no scope: the
            blank = self.svc.conn.execute(           # pass that knows the answer fills them in
                "update docs set scope=%s where corpus=%s and scope=''", (scope, corpus))
            if blank.rowcount:
                self.svc.conn.commit()
        return {"files": n_files, "chunks": n_chunks, "skipped": n_skip,
                "unchanged": n_unchanged, "removed": removed,
                "seconds": round(time.time() - t0, 3), "scope": scope, "class": klass,
                "corpus": corpus}

    def list(self, corpus: str | None = None) -> list[dict]:
        """The ledger: one row per indexed file. Without a corpus, every corpus's files.
        `scope` rides too: it is the corpus's home, and an operator comparing two stores wants
        to see it (a blank is a row from the first build, which index() restamps on its next pass)."""
        self._ensure()
        q = ("select path, corpus, scope, size, mtime, sha256, chunks, indexed_at from docs"
             + (" where corpus=%s" if corpus else "") + " order by corpus, path")
        with self.svc.lock:
            rows = self.svc.conn.execute(q, (corpus,) if corpus else ()).fetchall()
        return [{"path": r[0], "corpus": r[1], "scope": r[2], "size": r[3], "mtime": r[4],
                 "sha256": r[5], "chunks": r[6], "indexed_at": str(r[7])} for r in rows]

    def corpora(self) -> list[dict]:
        """Per-corpus tallies - the map a reader uses to know what the store can route over.
        `scope` is the corpus's home as the ledger records it (null when every row predates the
        column, which index() restamps on the file's next pass)."""
        self._ensure()
        with self.svc.lock:
            rows = self.svc.conn.execute(
                "select corpus, count(*), sum(chunks), max(indexed_at),"
                " string_agg(distinct nullif(scope, ''), ',') from docs"
                " group by corpus order by corpus").fetchall()
        return [{"corpus": r[0], "files": r[1], "chunks": r[2], "indexed_at": str(r[3]),
                 "scope": r[4]} for r in rows]

    def remove(self, corpus: str) -> bool:
        """Retire a corpus: its chunk rows go, its ledger goes. The FILES on disk are the
        territory and stay untouched (the text-plus-routing law: rows are the map).

        Rows are matched by provenance corpus, NOT by wiping the whole scope: two corpora may
        share an explicit scope, and the old scope-wide delete would retire the other one's
        rows too. Orphan rows (a killed pass, no ledger entry) are retired as well, so remove()
        answers for everything carrying the corpus name."""
        corpus = str(corpus or "").strip()
        if not corpus:
            return False
        self._ensure()
        with self.svc.lock:
            gone = [r[0] for r in self.svc.conn.execute(
                "delete from memories where provenance->>'corpus'=%s returning id",
                (corpus,)).fetchall()]
            cur = self.svc.conn.execute("delete from docs where corpus=%s", (corpus,))
            self.svc.conn.commit()
            if not gone and not cur.rowcount:
                return False
            self.svc._touched(reason="doc-remove")
            self.svc._dedupe_amend(retired=gone)
            self.svc._vdirty = True
        return True

    def _prune(self, corpus: str, seen: set) -> int:
        """Files that left the folder since the last pass: their ledger rows and their chunk
        rows go together (a map entry with no territory behind it is a lie).

        Rows whose file is not in this pass's `seen` set are retired even without a ledger row:
        a pass killed between its chunk writes and its ledger upsert leaves rows the ledger
        never learned (the 2026-10-31 founding pass left 66 for one Hume volume), and a
        ledger-only prune cannot see them. Returns the number of ledger files retired."""
        with self.svc.lock:
            stale = [r[0] for r in self.svc.conn.execute(
                "select path from docs where corpus=%s", (corpus,)).fetchall()
                if r[0] not in seen]
            gone = [r[0] for r in self.svc.conn.execute(
                "delete from memories where provenance->>'corpus'=%s"
                " and coalesce(provenance->>'file','') <> all(%s) returning id",
                (corpus, sorted(seen))).fetchall()]
            if stale:
                self.svc.conn.execute("delete from docs where corpus=%s and path = any(%s)",
                                      (corpus, stale))
            if stale or gone:
                self.svc.conn.commit()
                self.svc._touched(reason="doc-prune")
                self.svc._dedupe_amend(retired=gone)
                self.svc._vdirty = True
        return len(stale)

    @staticmethod
    def _read(p: Path) -> str:
        for enc in ("utf-8", "utf-16", "latin-1"):       # the corpus is a library, not a schema
            try:
                return p.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return p.read_text(encoding="utf-8", errors="replace")
