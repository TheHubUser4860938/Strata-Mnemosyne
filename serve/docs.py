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

import codecs
import hashlib
import os
import re
import time
from pathlib import Path

from .memory import CLASS_MAX, DOC_SOURCE_SQL, class_name, scope_name

DEFAULT_EXTS = (".txt", ".md")
CHUNK_CAP = 3900          # remember()'s 4,000-char ceiling minus the whitespace-collapse slack
ROW_MAX = 4000            # remember()'s hard ceiling; Docs.index clamps a larger --cap here
PARA_RE = re.compile(r"\n\s*\n+")

# The ledger's DDL. The store creates it at startup; an ATTACHING tool (m8_docs against a
# running server) creates it on first use, so a store that predates the table - every store,
# until its server's next boot - answers without a migration step. The two owners converge, not
# byte-identically: this copy carries the newest column (root), and _ensure() ADD COLUMNs the
# store's older copy up to it - IF NOT EXISTS makes either order idempotent.
_DOCS_DDL = """create table if not exists docs(
     corpus text not null,
     path text not null,
     scope text not null default '',
     size bigint not null default 0,
     mtime bigint not null default 0,
     sha256 text not null default '',
     chunks integer not null default 0,
     indexed_at timestamptz,
     root text not null default '',
     primary key (corpus, path))"""

#: the reading stage's two budgets (2026-11-02). A chunk row is up to ROW_MAX
#: characters; the tier-3 BLOCK shows the head of one, capped here, and the tool
#: arm (op=docs action=read) returns the passage the row points at.
PASSAGE_CAP = 1200               # what the block shows of one doc row
EXPAND_CAP = 6000                # what the tool arm returns: a full passage


def pack_chunks(text: str, cap: int = CHUNK_CAP, mode: str = "paragraphs") -> list[str]:
    """Split a document into rows of at most `cap` characters (whitespace-collapsed as stored).

    'paragraphs': pack whole blank-line-separated paragraphs while they fit, so a row ENDS at a
    paragraph boundary - a hard split only when one paragraph cannot fit alone.
    'fixed': the control windower, ~`cap` characters cut at word boundaries.
    In both modes every character of the source survives exactly once, in order (a word longer
    than `cap` is cut, because remember() refuses a row over its own ceiling)."""
    if cap < 32:
        raise ValueError(f"chunk cap must be >= 32 (got {cap})")
    if mode not in ("paragraphs", "fixed", "sections"):
        raise ValueError(f"mode: one of \"paragraphs\", \"fixed\", \"sections\" (got {mode!r})")
    if mode == "sections":
        return [t for t, _sec in pack_sections(text, cap=cap)]
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


#: A section heading, as the print editions write them: the Federalist papers carry
#: `FEDERALIST No. 10`, the Farrand records carry `No. 10`, modern files carry markdown
#: headings. A section is the unit a reader cites, so a row that lives inside ONE
#: section can be answered by paper, not by book - the fix for a panel whose gold is a
#: file+offset span while the corpus reprints the same papers in ten bindings.
SECTION_RE = re.compile(
    r"^(?:"
    r"THE\s+FEDERALIST\.?\s+No\.\s*[IVXLCDM]+\.?"      # Hamilton's Works: "THE   FEDERALIST.  No.  I."
    r"|FEDERALIST\s+No\.\s*(?:\d{1,3}|[IVXLCDM]+)\.?"   # the Gutenberg text: "FEDERALIST No. 10"
    r"|No\.\s*(?:\d{1,3}|[IVXLCDM]+)\.?(?:\s*[-\u2013]\s*\d{1,3}(?:\s*[-\u2013]\s*\d{1,3})?)?"
    r"|#{1,6}[ \t]+\S[^\n]*"                                # markdown: horizontal space only, so a
    r")\s*$", re.M)        # \s*$ : a print line ends with trailing spaces, and a
                            # heading that is not recognized is a section nobody finds
                            # bare "\s+" let a heading swallow the next three lines (audit
                            # 2026-11-07: "#\n\n\nBody text…" filed a section whose label was
                            # a paragraph, and 5,661 of the sections index's rows are markdown)

ROMAN = re.compile(r"^(M{0,4})(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ROMAN_VAL = (("M", 1000), ("CM", 900), ("D", 500), ("CD", 400), ("C", 100), ("XC", 90),
              ("L", 50), ("XL", 40), ("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1))


def section_paper(section: str) -> int | None:
    """The paper NUMBER a section heading names - arabic or roman, from any book.

    The point of tagging a row with its section is that the binding stops mattering:
    a row in Hamilton's Works headed `THE FEDERALIST. No. X.` and a row in the
    Gutenberg text headed `FEDERALIST No. 10` name the SAME paper, and a caller who
    asks for paper 10 should be able to compare them. Returns None for a heading that
    names no number (a markdown title, "Book II").
    """
    if not section:
        return None
    m = re.search(r"No\.?\s*([0-9]{1,3}|[IVXLCDM]+)\.?", section, re.I)
    if not m:
        return None
    tok = m.group(1).upper()
    if tok.isdigit():
        return int(tok)
    if not ROMAN.match(tok):
        return None
    n, i = 0, 0
    while i < len(tok):
        for sym, val in _ROMAN_VAL:
            if tok.startswith(sym, i):
                n += val
                i += len(sym)
                break
        else:
            return None
    return n or None


def pack_sections(text: str, cap: int = CHUNK_CAP) -> list[tuple[str, str]]:
    """Rows of at most `cap` characters, each tagged with the SECTION it belongs to.

    Returns [(row, section)] in document order, every character surviving exactly once -
    the contract `pack_chunks` keeps. A section starts at its heading and runs to the
    next one, and the heading is the first thing in the segment, so the row that opens a
    paper CONTAINS its title. Text before the first heading carries section "".

    The section rides into the row's provenance, which is the point: a hit in
    `DOC/FOUNDING/HAMILT` and a hit in `DOC/FOUNDING/FEDERAL` can then answer for the
    SAME paper, and the binding stops being a property of the binding.
    """
    if cap < 32:
        raise ValueError(f"chunk cap must be >= 32 (got {cap})")
    heads = [(m.start(), m.group(0).strip()) for m in SECTION_RE.finditer(text)]
    out: list[tuple[str, str]] = []
    if not heads:
        return [(row, "") for row in pack_chunks(text, cap=cap, mode="paragraphs")]
    if heads[0][0] > 0:
        for row in pack_chunks(text[:heads[0][0]], cap=cap, mode="paragraphs"):
            out.append((row, ""))
    starts = [h[0] for h in heads] + [len(text)]
    for i, (at, head) in enumerate(heads):
        seg = text[at:starts[i + 1]]
        if not seg.strip():
            continue
        for row in pack_chunks(seg, cap=cap, mode="paragraphs"):
            out.append((row, head))
    return out


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
        self._readers: dict[str, DocReader] = {}   # corpus -> the cached file reader
        self._ready = False                        # the DDL has run in this process

    def _ensure(self):
        """The ledger exists before any verb reads it - the attacher's path (a running server
        booted on the old DDL list), and a fresh store's first docs call before its own
        startup ran. One IF NOT EXISTS, idempotent against the store's own _startup.
        Run ONCE per process (audit 2026-11-07): three DDL statements on every docs verb,
        `read()` included, was the cheapest round trip to shave off the reading stage."""
        if self._ready:
            return
        with self.svc.lock:
            self.svc.conn.execute(_DOCS_DDL)
            # 2026-11-02, the reading stage: a store indexed before this build has
            # the table and not the column. ADD COLUMN IF NOT EXISTS is the whole
            # migration - a blank root means "indexed before we recorded it", which
            # read() reports instead of guessing a folder.
            self.svc.conn.execute("alter table docs add column if not exists"
                                  " root text not null default ''")
            # the corpus-keyed index (audit F15, 2026-11-03) - same statement the store's
            # _PG_DDL runs, so the attach lane and the server leave the ledger identically indexed.
            self.svc.conn.execute(
                "create index if not exists mem_doc_corpus on memories ((provenance->>'corpus'))"
                " where " + DOC_SOURCE_SQL)
            self.svc.conn.commit()
            self._ready = True

    def index(self, folder, corpus: str, *, klass: str | None = None, scope: str | None = None,
              cap: int = CHUNK_CAP, mode: str = "paragraphs", exts=DEFAULT_EXTS,
              guard: bool = False, force: bool = False) -> dict:
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
                # FORCE (2026-11-02): the chunker MODE is not in the stat key, so a
                # paragraphs -> sections re-index of an untouched folder is a no-op
                # sweep. A mode/cap sweep says so out loud.
                digest = None
                if row is not None and not force and int(row[0]) == st.st_size \
                        and int(row[1]) == _mtime_us(st):
                    n_unchanged += 1
                    continue                            # the morning pass: stat, keep, move on
                digest = _sha256(p)                     # the authority: cheap gate moved -> hash
                if row is not None and not force and row[2] == digest:
                    with self.svc.lock:                 # touched, not changed: the stamp rides
                        self.svc.conn.execute(
                            "update docs set mtime=%s where corpus=%s and path=%s",
                            (_mtime_us(st), corpus, rel))
                        self.svc.conn.commit()
                    n_unchanged += 1
                    continue
                text = self._read(p)
                # 2026-11-02, the paper-aware mode: 'sections' cuts at the headings the
                # print editions write, so a row lives inside ONE paper and carries it in
                # its provenance. 'paragraphs' and 'fixed' carry every row as section "".
                pairs = (pack_sections(text, cap=cap) if mode == "sections"
                         else [(c, "") for c in pack_chunks(text, cap=cap, mode=mode)])
                chunks = [t for t, _s in pairs]
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
                for i, (chunk, section) in enumerate(pairs):
                    pos = collapsed.find(chunk, cur)  # anchor it: a cut long word joins with no
                    off = pos if pos >= 0 else cur    # space and a packed paragraph with one, so
                    prov = {"file": rel, "corpus": corpus, "offset": off,
                            "n": i, "n_chars": len(chunk), "sha256": doc_sha,
                            "chunk_sha256": hashlib.sha256(
                                chunk.encode("utf-8")).hexdigest()}
                    if section:                      # THE PAPER, not the binding (sections mode)
                        prov["section"] = section[:80]
                        # The paper number is parsed from the WHOLE heading, not the 80-char label
                        # (audit 2026-11-07): a heading that names `No. 90` past char 80 used to
                        # route to nothing, because the label was cut before section_paper saw it.
                        paper = section_paper(section)
                        if paper:
                            prov["paper"] = paper
                    self.svc.remember(chunk, scope=scope, source=source, guard=guard,
                                      exact=False, klass=klass, provenance=prov)
                    cur = off + len(chunk)            # the next row starts here (a cut word) or
                                                      # one char later (the space between rows)
                with self.svc.lock:
                    self.svc.conn.execute(
                        "insert into docs(path, corpus, scope, size, mtime, sha256, chunks,"
                        " indexed_at, root) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        " on conflict (corpus, path) do update set size=excluded.size,"
                        " mtime=excluded.mtime, sha256=excluded.sha256, chunks=excluded.chunks,"
                        " scope=excluded.scope, indexed_at=excluded.indexed_at,"
                        " root=excluded.root",
                        # scope=excluded.scope is belt-and-braces, not the load-bearing part: the
                        # guard above means a stored scope cannot drift, and the blank-fill after
                        # the walk repairs the rows the first build left empty (so the upsert arm
                        # has no test of its own - say so rather than imply one)
                        (rel, corpus, scope, st.st_size, _mtime_us(st), doc_sha, len(chunks),
                         self.svc._dt(time.time()), str(root)))
                    self.svc.conn.commit()
                n_files += 1
                n_chunks += len(chunks)
                n_skip += sum(1 for c in chunks if len(c) >= cap)   # a full row = a split paragraph
        removed = self._prune(corpus, seen)
        # The cached reader follows the ROOT (audit 2026-11-07): reader() builds one DocReader per
        # corpus and caches it, set_root pops it, and index() - the other verb that moves a
        # corpus's address - did not. Re-index a corpus from a new folder and docs.read kept
        # cutting passages out of the OLD one: ok:true, plausible text, match:false.
        self._readers.pop(corpus, None)
        with self.svc.lock:                         # legacy ledger rows carried no scope: the
            blank = self.svc.conn.execute(           # pass that knows the answer fills them in
                "update docs set scope=%s where corpus=%s and scope=''", (scope, corpus))
            if blank.rowcount:
                self.svc.conn.commit()
        return {"files": n_files, "chunks": n_chunks, "skipped": n_skip,
                "unchanged": n_unchanged, "removed": removed,
                "seconds": round(time.time() - t0, 3), "scope": scope, "class": klass,
                "corpus": corpus, "root": str(root)}

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

    def reconcile(self, corpus: str | None = None) -> int:
        """Rewrite the ledger's per-file `chunks` to the LIVE active-row count (audit D3,
        2026-11-03). The exact-dup fold retires rows (invalidate, then purge) and the ledger's
        stamped count does not move with them, so `corpora()`/`list()` and the Docs tile over-
        report - on this store by 130 (the Gutenberg license tail, shared across books). The
        ledger is a cache of the truth, not the truth; this re-derives it. Returns files moved."""
        self._ensure()
        # Driven by the LEDGER, not by the live counts (audit 2026-11-07): the loop walked a
        # `group by` over rows that EXIST, so a file whose last row was folded kept its stale count
        # forever - and a fully-folded book is exactly what a reconciliation exists to catch. One
        # UPDATE per ledger row; a file with no live rows now says 0.
        args: list = []
        only = ""
        if corpus:
            only = " and d.corpus=%s"
            args = [corpus]
        live = ("select count(*) from memories m"
                " where m.invalid_at is null and m.provenance->>'corpus' = d.corpus"
                "   and m.provenance->>'file' = d.path")
        with self.svc.lock:
            moved = self.svc.conn.execute(
                f"update docs d set chunks = ({live}) where d.chunks <> ({live})" + only,
                args).rowcount
            self.svc.conn.commit()
        return int(moved)

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

    # -- the reading stage (2026-11-02) ------------------------------------
    def corpus_root(self, corpus: str) -> str:
        """The folder a corpus was indexed from - the territory a hit expands into.
        '' when the ledger predates the column: say so, do not guess a folder."""
        self._ensure()
        with self.svc.lock:
            row = self.svc.conn.execute(
                "select root from docs where corpus=%s and root<>'' limit 1",
                (corpus,)).fetchone()
            self.svc.conn.commit()
        return row[0] if row else ""

    def set_root(self, corpus: str, root: str | Path) -> int:
        """Stamp the folder a corpus lives in, WITHOUT re-chunking it (2026-11-02).

        A store indexed before the `root` column has 34,478 good rows and no
        address; re-indexing to get the address costs the whole pass. This is the
        one UPDATE. It validates the folder, and read() validates the SPINE - so a
        wrong stamp shows up as rows that do not match their own text, not as a
        silent success.
        """
        self._ensure()
        r = Path(str(root)).expanduser()
        if not r.is_dir():
            raise ValueError(f"not a directory: {r}")
        with self.svc.lock:
            n = self.svc.conn.execute("update docs set root=%s where corpus=%s",
                                      (str(r), corpus)).rowcount
            self.svc.conn.commit()
        # Drop the cached reader (audit D4, 2026-11-03): reader() builds a DocReader once per
        # corpus, so after a root move the next read cut the passage out of the OLD folder -
        # a same-named file on the new mount returned plausible, wrong text with ok:true.
        self._readers.pop(corpus, None)
        return int(n)

    def set_class(self, corpus: str, klass: str, path: str | None = None) -> int:
        """Re-shelve a corpus's rows, or one file's rows, WITHOUT re-chunking (2026-11-02).

        The class is a column on the row, so a cutter is one UPDATE: ids survive,
        offsets survive, and the vectors survive (they key on id). The cutters give the
        browse map a drawer per book - `DOC/FOUNDING/HAMILT` beside `DOC/FOUNDING/FEDER`
        - and a filtered request can name one book. Prefix filters keep working: a query
        for DOC/FOUNDING reaches every cutter under it.
        """
        self._ensure()
        klass = class_name(klass)
        if not klass:
            raise ValueError("class must be a call number like DOC/FOUNDING/HAMILT")
        q = ("update memories set class=%s, updated_at=updated_at"
             " where invalid_at is null and provenance->>'corpus'=%s")
        args: list = [klass, corpus]
        if path is not None:
            q += " and provenance->>'file'=%s"
            args.append(str(path))
        with self.svc.lock:
            n = self.svc.conn.execute(q, args).rowcount
            self.svc.conn.commit()
            self.svc._vdirty = True        # the matrix carries a CLASS column for the
                                           # cosine arm's shelf_mask (classify's lesson)
        return int(n)

    def cutters(self, corpus: str, width: int = 6) -> dict[str, str]:
        """A cutter per file: the stem's letters, upper-cased, made unique in file-name
        order, so the same folder always produces the same shelf codes. `hamilton_works_
        cu32371…` -> `HAMILT`; a collision gets a digit suffix (`MADISO`, `MADIS1`)."""
        self._ensure()
        with self.svc.lock:
            paths = [r[0] for r in self.svc.conn.execute(
                "select path from docs where corpus=%s order by path", (corpus,)).fetchall()]
            self.svc.conn.commit()
        used: set[str] = set()
        seen: dict[str, int] = {}
        out: dict[str, str] = {}
        for rel in paths:
            stem = re.sub(r"[^A-Za-z]", "", Path(str(rel)).stem)[:width].upper() or "DOC"
            n = seen.get(stem, 0)
            seen[stem] = n + 1
            cut = stem if n == 0 else f"{stem[:width - 1]}{n}"
            while cut in used:                      # a file whose own stem is a
                n += 1                               # collision code (DECLA1.txt) must
                seen[stem] = n + 1                   # not be handed that code twice
                cut = f"{stem[:width - 1]}{n}"
            used.add(cut)
            out[str(rel)] = cut
        return out

    def reader(self, corpus: str) -> DocReader:
        r = self._readers.get(corpus)
        if r is None:
            root = self.corpus_root(corpus)
            if not root:
                raise ValueError(f"corpus {corpus!r} records no root folder - re-index it "
                                 "once (tools/m8_docs.py) to enable passage reads")
            r = self._readers[corpus] = DocReader(root)
        return r

    def read(self, corpus: str, path: str, offset: int = 0, n: int = 0, *,
             before: int = 0, after: int = 0, cap: int = EXPAND_CAP,
             expect: str | None = None) -> dict:
        """Cut the passage a row points at out of the FILE.

        Offsets count the WHITESPACE-COLLAPSED body, the same space index() stored
        them in (the spine law: a row's text is a substring of that body, and the
        2026-10-31 build measured 0 of 34,478 rows missing their own text). With
        `expect` (the row's own text) the result carries `match`, which is that
        check run against the file, not against the store.

        Two numbers, deliberately: `n` is the WINDOW the reader asked for, `chars`
        is what came back after the cap - a clipped passage is shorter than its
        window, and a caller who wants to continue reads from offset + chars.
        """
        try:
            body, stamp = self.reader(corpus).body(str(path))
        except (OSError, ValueError) as exc:
            return {"ok": False, "corpus": corpus, "file": str(path),
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        offset, n = int(offset), max(0, int(n))
        # Clamped at BOTH ends (audit 2026-11-07): an offset past EOF used to answer ok:true with a
        # NEGATIVE n, so a caller that continues at `offset + n` walked backwards through the file.
        lo = min(max(0, offset - int(before)), len(body))
        hi = (min(len(body), offset + n + int(after)) if n or after
              else min(len(body), lo + int(cap)))
        text, truncated = _clip(body[lo:hi], int(cap))
        return {"ok": True, "corpus": corpus, "file": str(path), "offset": lo,
                "n": hi - lo, "chars": len(text), "total": len(body),
                "truncated": truncated, "mtime": stamp, "text": text,
                "match": (body[offset:offset + len(expect)] == expect
                          if expect else None)}

    def expand(self, hit: dict, *, window: int = 0, cap: int = EXPAND_CAP) -> dict:
        """read() driven by a search hit: the provenance is the join.

        A hit's provenance arrives as a dict from search() and as a JSON string
        from a raw row read, so both are accepted. A hit with no provenance is a
        fact row, not a doc row, and says so.
        """
        prov = hit.get("provenance") if isinstance(hit, dict) else None
        if isinstance(prov, str):
            import json
            try:
                prov = json.loads(prov)
            except ValueError:
                prov = None
        if not isinstance(prov, dict) or not prov.get("corpus") or not prov.get("file"):
            return {"ok": False, "error": "this hit carries no document provenance",
                    "id": hit.get("id") if isinstance(hit, dict) else None}
        n = int(prov.get("n_chars") or 0) or len(str(hit.get("text") or ""))
        return self.read(str(prov["corpus"]), str(prov["file"]),
                         int(prov.get("offset") or 0), n,
                         before=int(window), after=int(window), cap=cap,
                         expect=str(hit.get("text") or "") or None)

    def rerank(self, query: str, hits: list[dict], ask=None, **kw) -> list[dict]:
        """Ask the model which candidates answer `query`, and reorder. Opt-in:
        with no `ask` (and no `svc.rerank_ask`) the order is the retrieval's, so
        turning the arm on cannot change a store that never asked for it."""
        ask = ask or getattr(self.svc, "rerank_ask", None)
        if not ask or not hits:
            return list(hits)
        return rerank(query, hits, ask, **kw)

    @staticmethod
    def _read(p: Path) -> str:
        # The corpus is a library, not a schema (audit 2026-11-07): the old ladder tried utf-16
        # second, and EVERY even-length latin-1 file decodes as utf-16 - "Café séjour déjà." (18
        # bytes) came back as 慃\ue966猠櫩畯\ue06aਮ and got embedded that way, with a self-consistent
        # spine, so nothing looked wrong. utf-16 is now chosen by its BOM, and utf-8-sig first so
        # a BOM stops riding in row 0 and stoppering the first heading.
        if p.stat().st_size >= 2:
            with p.open("rb") as probe:
                head = probe.read(2)
            if head in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
                try:
                    return p.read_text(encoding="utf-16")
                except UnicodeDecodeError:
                    pass
        for enc in ("utf-8-sig", "latin-1"):
            try:
                return p.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return p.read_text(encoding="utf-8", errors="replace")


# ---- 2026-11-02: the reading stage ----------------------------------------
# A hit is a MAP entry: the row's text is one <=3,900-char chunk, and the file
# is the territory. Three things a reader needs, in order of cost:
#
#   read()    the passage a row points at, cut out of the file by its provenance
#   expand()  the same thing from a search hit (the provenance is the join)
#   rerank()  ask the served model which of the candidates answers the question
#
# The BLOCK shows PASSAGE_CAP characters of a row; the TOOL arm returns
# EXPAND_CAP. That split is the whole reading stage's budget story: a chunk row
# is 3,900 chars, eight of them is 31 KB of context, and the head of a passage
# is what pays for itself in the block.
def _collapse(text: str) -> str:
    """The body a row's `offset` counts in: whitespace collapsed, as index() stores it."""
    return " ".join(text.split())


class DocReader:
    """The file side of the document index: cached, collapsed, offset-honest.

    One instance per MemoryService (`svc.docs.reader` is not a thing - the methods
    live on Docs and hang their cache off `svc.doc_cache`), so an index pass and a
    read pass see the same bytes without re-reading a 6 MB paper per hit.
    """

    def __init__(self, root: Path | str, keep: int = 8):
        self.root = Path(str(root)).expanduser()
        self.keep = max(1, int(keep))
        self.files: dict[str, tuple[int, str]] = {}      # path -> (mtime_us, collapsed)

    def body(self, rel: str) -> tuple[str, int]:
        """The file's collapsed text, and the mtime stamp it was read at.
        Contained (audit D2, 2026-11-03): a caller-supplied path (op=docs action=read
        carries `path` on the wire) resolves inside the corpus root - '../outside.txt'
        walks the shelf back onto the filesystem, so a client that can POST /memory
        reads any file the server can open. Resolved-then-compared, so symlinks count."""
        p = (self.root / rel)
        rp, rr = p.resolve(), self.root.resolve()
        if rr not in rp.parents and rp != rr:
            raise ValueError(f"path {rel!r} is not inside the corpus root {rr}")
        st = p.stat()
        stamp = _mtime_us(st)
        hit = self.files.get(rel)
        if hit and hit[0] == stamp:
            return hit[1], stamp
        body = _collapse(Docs._read(self.root / rel))
        self.files[rel] = (stamp, body)
        while len(self.files) > self.keep:                # a corpus is a library
            self.files.pop(next(iter(self.files)))        # FIFO, 8 files, ~40 MB at most
        return body, stamp


def _clip(text: str, cap: int) -> tuple[str, bool]:
    """Cut at `cap`, then at the last word boundary, and say whether it was cut."""
    if len(text) <= cap:
        return text, False
    head = text[:cap]
    cut = head.rfind(" ")
    return (head[:cut] if cut > cap // 2 else head), True


#: The listwise prompt. Shaped for a small local model: one instruction, the
#: passages, and a reply format a parser cannot misread. Kept in one place so an
#: eval can A/B the phrasing without touching the ranking code.
RERANK_PROMPT = ("You are ranking passages by how well each one ANSWERS the question.\n\n"
                 "Question: {q}\n\n{body}\n\n"
                 "Reply with the passage numbers only, best first, separated by commas.")


def _parse_order(text: str, n: int) -> list[int]:
    """The model's ranking as indices, 0-based. Numbers it skipped sort last, in
    the order retrieval put them - a rerank reorders, it never drops (cap not
    quota, m4_blockrule's law)."""
    seen: list[int] = []
    for tok in re.findall(r"\d+", text or ""):
        i = int(tok) - 1
        if 0 <= i < n and i not in seen:
            seen.append(i)
    seen += [i for i in range(n) if i not in seen]
    return seen


def rerank(query: str, hits: list[dict], ask, *, k: int = 8, cap: int = 900,
           label: str = "text") -> list[dict]:
    """Reorder the top `k` candidates by an LLM's judgement; keep the tail's order.

    `ask` is any callable prompt -> text, which is what makes this testable with a
    stub and what lets the server use its own engine. `rerank` is stamped on each
    moved hit so a run says what the arm did to it (the scar stays visible).
    """
    head = list(hits)[:k]
    tail = list(hits)[k:]
    if len(head) < 2:
        return list(hits)
    body = "\n\n".join(f"{i + 1}. {_clip(str(h.get(label) or ''), cap)[0]}"
                       for i, h in enumerate(head))
    order = _parse_order(ask(RERANK_PROMPT.format(q=query, body=body)), len(head))
    out = []
    for rank, i in enumerate(order):
        h = dict(head[i])
        h["rerank"] = rank
        out.append(h)
    return out + tail


def ask_url(url, *, model: str = "", max_tokens: int = 60, timeout: float = 20.0):
    """A prompt -> text callable over the box's own OpenAI surface.

    The store keeps no model-client dependency (serve/ runs without any SDK), so
    the rerank arm asks the server the way every other app does - one POST. This
    is the wiring the config turns on (`memory.rerank = "on"` for this process's
    port, or a URL for a second model); with it off, `Docs.rerank` returns the
    retrieval's own order, byte-identical to the pre-reading-stage path.
    """
    import json
    import urllib.request

    def ask(prompt: str) -> str:
        # `url` may be a callable: the server wires this before it knows the port
        # it bound (--port 0), so the address is resolved at ask time.
        target = url() if callable(url) else url
        body = json.dumps({"model": model or "strata", "temperature": 0.0,
                           "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(target, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:     # noqa: S310
            data = json.loads(resp.read().decode())
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return str(msg.get("content") or ch.get("text") or "")

    return ask
