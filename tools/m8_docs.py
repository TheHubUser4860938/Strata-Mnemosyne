#!/usr/bin/env python3
"""m8_docs - index a folder of text into the store as chunk rows (the document index, 2026-10-31).

The server's twin (op=docs on /memory) needs a boot that carries it; this tool runs against a
LIVE store today - the attach law (ADR-002 R0b): attaching starts nothing when a server runs
the cluster, and an attacher leaving does not stop it. Same rows, same shelf, same ledger
either way; the sweep and the running engine see the new rows on their next read (the
embedded-count check in _vec_matrix is the pickup, tools/m4_embed.py's precedent).

The corpus path law: TEXT + ROUTING. The file stays the territory on disk; the store keeps
the map - one row per <=3,900-char chunk, scope per corpus, shelf DOC/<CORPUS>, provenance
{file, corpus, offset, n, sha256, chunk_sha256} that expands a hit back into the passage.
INCREMENTAL: a rescan stats each file against the docs ledger and re-chunks only what moved
(the morning pass over an unchanged folder costs one stat() sweep, not the reported 10-15
minutes).

Lexical-first by default (measured: 27 ms/row on 3,900-char chunks, 13.3 min for a 118 MB
corpus); --embed runs the semantic arm inline (measured: 2.4 chunks/s on 8 threads, ~3.4 h
for the same corpus), and tools/m4_embed.py closes the vector gap for rows written before.

  python3 tools/m8_docs.py FOLDER --corpus founding [--class DOC/FOUNDING] [--scope doc-founding]
      [--mode paragraphs|fixed] [--cap 3900] [--embed [--model DIR] [--threads 8]]
      [--list [CORPUS] | --remove CORPUS] [--dir Strata-data/memory-eval]
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "serve")):
    if p not in sys.path:
        sys.path.insert(0, p)
from strata_control.datafolder import data_dir          # noqa: E402  the one data folder
from serve.memory import attach                          # noqa: E402


class _AttachingStore:
    """The MINIMAL service shape serve/docs.py drives: conn, lock, remember, and the three
    cache-nudge hooks. The hooks are no-ops here on purpose - an attacher owns no caches; the
    SERVER process rebuilds its own matrix and token table by the stamp checks when it next
    reads (m4_embed's exact pickup law). remember() is the store's own method, bound to this
    duck-type: it reads exactly the attributes here (conn, lock, embedder, auto_shelve,
    _dt, _touched, _vdirty, _dedupe_amend)."""

    def __init__(self, conn, embedder=None):
        import serve.memory as _m
        self.conn, self.lock, self.embedder = conn, threading.Lock(), embedder
        self.auto_shelve = False
        self.max_memories = 0             # 0 = unlimited: budget eviction never fires (this box's law)
        self._vdirty = False
        for _n in ("auto_classify", "_semantic_dupe", "_execmany", "_bump"):
            setattr(self, _n, (lambda f: lambda *a, **kw: f(self, *a, **kw))(
                getattr(_m.MemoryService, _n)))   # the store's own methods, bound to this duck
        self.remember = lambda text, **kw: _m.MemoryService.remember(self, text, **kw)

    def _touched(self, ids=None, reason=""):
        pass

    def _dedupe_amend(self, *a, **kw):
        pass

    def _dt(self, epoch):
        import serve.memory as _m
        return _m.MemoryService._dt(epoch)      # the store's own epoch->timestamptz boundary

    def close(self):
        self.conn.close()


def build(dir_arg: str, embed_model: str | None, threads: int) -> _AttachingStore:
    try:
        conn = attach(str(dir_arg))
    except Exception as exc:                       # noqa: BLE001 - a clear no beats a traceback
        raise SystemExit(f"cannot attach {dir_arg}: {type(exc).__name__}: {str(exc)[:140]} - "
                         "is this a Postgres store?")
    emb = None
    if embed_model:
        from serve.embedder import create
        emb = create(embed_model, threads=threads)
    return _AttachingStore(conn, emb)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", help="the directory of text files to index")
    ap.add_argument("--corpus", default="", help="the shelf family / scope name (required for index)")
    ap.add_argument("--class", dest="klass", default=None, help="shelf (default DOC/<CORPUS>)")
    ap.add_argument("--scope", default=None, help="store scope (default doc-<corpus>)")
    ap.add_argument("--mode", choices=("paragraphs", "fixed"), default="paragraphs")
    ap.add_argument("--cap", type=int, default=3900, help="row ceiling in chars (<= 4000)")
    ap.add_argument("--exts", default=".txt,.md", help="comma-separated suffixes to index")
    ap.add_argument("--embed", action="store_true", help="embed each chunk at write time (slow arm)")
    ap.add_argument("--model", default=str(data_dir(ROOT) / "embeddings/embeddinggemma-2"),
                    help="embedder dir (default: the box's live model)")
    ap.add_argument("--threads", type=int, default=8, help="embedder CPU threads")
    ap.add_argument("--list", nargs="?", const="", metavar="CORPUS", help="the ledger, then exit")
    ap.add_argument("--remove", metavar="CORPUS", help="retire a corpus's rows and ledger, then exit")
    ap.add_argument("--dir", default=str(data_dir(ROOT) / "memory-eval"), help="the store dir")
    a = ap.parse_args()

    need_embed = a.embed and not (a.remove or a.list is not None)
    svc = build(a.dir, a.model if need_embed else None, a.threads)
    from serve.docs import Docs
    svc.docs = Docs(svc)
    try:
        if a.remove:
            print(json.dumps({"removed": svc.docs.remove(a.remove)}))
            return 0
        if a.list is not None:
            print(json.dumps({"files": svc.docs.list(a.list or None),
                              "corpora": svc.docs.corpora()}, indent=1))
            return 0
        if not a.folder:
            ap.error("name a FOLDER to index, or use --list / --remove")
        t0 = time.time()
        r = svc.docs.index(a.folder, a.corpus, klass=a.klass, scope=a.scope, cap=a.cap,
                           mode=a.mode, exts=tuple("." + x.strip().lstrip(".")
                                                   for x in a.exts.split(",") if x.strip()))
        print(json.dumps(r, indent=1))
        print(f"m8_docs: {r['files']} files -> {r['chunks']} chunk rows on {r['class']} "
              f"(scope {r['scope']}), {r['unchanged']} unchanged, {r['removed']} pruned, "
              f"{time.time() - t0:.1f} s, embed={'on' if need_embed else 'off'}", file=sys.stderr)
        return 0
    finally:
        svc.close()


if __name__ == "__main__":
    sys.exit(main())
