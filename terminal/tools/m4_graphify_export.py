#!/usr/bin/env python3
"""m4_graphify_export.py — dump the store's fact rows to a markdown corpus.

Graphify reads documents, not a database, so this is the bridge: one markdown file per
shelf part, one section per fact, each carrying its row id, date and confidence so a
graph node traces back to the ledger.

Shelves split at --per-file facts. That is not tidiness: graphify makes the model *write*
a JSON node-and-edge list for every file in a chunk, and on this box a chunk's 16,384-token
output cap is what truncated the runs. Small files, small chunks, whole answers.
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

from serve.memory import attach

SLUG = re.compile(r"[^a-z0-9]+")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="bench/p1/graphify-corpus", help="corpus directory")
    ap.add_argument("--store", default="/home/eugene/Strata-data/memory-eval", help="store dir")
    ap.add_argument("--per-file", type=int, default=40, help="max facts per markdown file")
    ap.add_argument("--docs", action="store_true", help="include doc-index chunks, not just facts")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.md"):
        stale.unlink()

    where = "invalid_at IS NULL" + ("" if args.docs else " AND source NOT LIKE 'doc-index%'")
    conn = attach(args.store)          # starts nothing; an attacher leaving stops nothing
    try:
        rows = conn.execute(
            "SELECT id, class, text, created_at, confidence FROM memories WHERE "
            + where + " ORDER BY class, created_at"
        ).fetchall()
    finally:
        conn.close()

    by_shelf = defaultdict(list)
    for row in rows:
        by_shelf[row[1] or "UNSHELVED"].append(row)

    written = 0
    for cls, items in sorted(by_shelf.items()):
        slug = SLUG.sub("-", cls.lower()).strip("-") or "unshelved"
        split = len(items) > args.per_file
        for part, start in enumerate(range(0, len(items), args.per_file), 1):
            chunk = items[start:start + args.per_file]
            body = ["# " + cls + (" — part " + str(part) if split else "") + "\n",
                    str(len(chunk)) + " facts from the Strata memory store.\n"]
            for rid, _, text, created, conf in chunk:
                body.append("## fact " + str(rid) + "\nSaid " + str(created)
                            + " · confidence " + str(conf) + "\n\n" + (text or "").strip() + "\n")
            name = slug + (("-%02d" % part) if split else "")
            (out / (name + ".md")).write_text("\n".join(body), encoding="utf-8")
            written += 1

    print(str(len(rows)) + " facts -> " + str(written) + " files in " + str(out)
          + " (" + str(args.per_file) + " facts per file)")


if __name__ == "__main__":
    main()

