#!/usr/bin/env python3
"""Strata Graphify CLI — the graph pass, from the command line.

    python -m strata.graphify.cli status              # tile numbers, as JSON
    python -m strata.graphify.cli graph               # same, plus the path
    python -m strata.graphify.cli build               # full pass over every shelf
    python -m strata.graphify.cli update              # pass over the facts the harvest noted
    python -m strata.graphify.cli note 1234 1235      # record ids for the next pass
    python -m strata.graphify.cli pending             # ids waiting
    python -m strata.graphify.cli view               # compact nodes+communities (the page's data)

A pass is LLM work on the served model, one chunk at a time, so it is slow and it is
free. `build` blocks and prints progress per chunk; `update` is what the harvest calls.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import DIR_NAME, StrataGraphify


def _out(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="strata graphify", description=__doc__.splitlines()[0])
    ap.add_argument("--store", default=None, help="store directory (default: the box's)")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="graph tile numbers")
    sub.add_parser("graph", help="same as status, with the file path")
    sub.add_parser("view", help="compact node + community payload the web page draws")
    sub.add_parser("pending", help="fact ids noted since the last pass")
    sub.add_parser("update", help="pass over the pending facts and merge")

    c = sub.add_parser("cover", help="drain the store: merge passes until every row is named")
    c.add_argument("--per-file", type=int, default=10, help="facts per corpus file (10 names ~1 concept per 1.5 facts)")
    c.add_argument("--files-per-chunk", type=int, default=6, help="files per LLM call")
    c.add_argument("--max-passes", type=int, default=12, help="stop after N passes")

    b = sub.add_parser("build", help="full pass over every shelf")
    b.add_argument("--bridge", action="store_true",
                   help="one pass over the graph's own communities, to put edges BETWEEN them")
    b.add_argument("--async", dest="background", action="store_true",
                   help="start the pass and return (progress lands in progress.json)")
    n = sub.add_parser("note", help="record fact ids for the next pass")
    n.add_argument("ids", nargs="+", type=int)

    a = ap.parse_args(argv)
    t0 = time.time()
    import os
    store = a.store or os.environ.get("STRATA_STORE", "/home/eugene/Strata-data/memory-eval")
    g = StrataGraphify(store)

    if a.command in ("status", "graph"):
        s = g.summary()
        if a.command == "graph":
            s["graph_path"] = str(g.graph_path)
        _out(s)
    elif a.command == "view":
        _out(g.view())
    elif a.command == "pending":
        _out({"pending": g.pending_ids(), "due": g.due()})
    elif a.command == "note":
        _out({"noted": g.note(a.ids)})
    elif a.command == "update":
        ids = g.pending_ids()
        if not ids:
            _out({"status": "nothing pending"})
            return 0
        t0 = time.time()
        _out(g.build(ids=ids, full=False))
    elif a.command == "cover":
        s = g.cover(per_file=a.per_file, files_per_chunk=a.files_per_chunk,
                    max_passes=a.max_passes,
                    on_progress=lambda p, res: print(
                        f"  cover pass {p}: {res.get('status')} · {res.get('nodes')} nodes"
                        f" · {res.get('communities')} communities", file=sys.stderr, flush=True))
        _out(s)
    elif a.command == "build":
        if a.bridge:
            _out(g.bridge())
            return 0
        if a.background:
            _out(g.build_in_background(full=True))
            return 0
        # One code path with the web page: the pass runs on a thread, progress.json is the
        # truth, and this loop only prints when the numbers move.
        g.build_in_background(full=True)
        last = None
        while True:
            p = g._progress()
            if (p.get("done"), p.get("total"), p.get("running")) != last:
                print(f"  chunk {p.get('done')}/{p.get('total')}"
                      + (" extracting…" if p.get("running") else ""), file=sys.stderr, flush=True)
                last = (p.get("done"), p.get("total"), p.get("running"))
            if not p.get("running"):
                break
            time.sleep(15)
        if p.get("error"):
            _out({"status": "failed", "error": p["error"]})
            return 1
        _out({**g.summary(), "elapsed_s": round(time.time() - t0, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
