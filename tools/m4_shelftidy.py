#!/usr/bin/env python3
"""m4_shelftidy - the two edges of a shelf: too wild, too fine.

Tonight's sequence, measured:

  583 wild rows (26%)  ->  the clerk files them  ->  63 wild, 243 shelves
                          ...and the tail is 136 shelves of 1-2 rows,
                          25 of them top-level marks the clerk invented (FLUOR,
                          DANTE, CELLB, QFTD, TOKEN...) for one fact each.

So sorting is two rules, not one:

  TOPS     a subject family earns a top category. The clerk names drawers well and
           tops badly, so this pass asks it for the SHORTEST list of tops that covers
           the invented ones (SCI for the biology and physics marks, LIT for Dante),
           and applies the map as `TOP/CUTTER` - the cutter survives, the invention
           becomes a drawer under a family a person can say out loud.

  THE 3-ROW BAR   a cutter earns its drawer at three rows. Below that it rides the
           family: `POL/TRUMP` (1 row) rolls to `POL`, and POL stops being 29 shelves
           of mostly one card each. Three, not five, because the store is 2.2k rows:
           at five the families get fat again (the bar is a knob, `--bar`).

Both edges are UPDATEs on the class column - ids, text, offsets and vectors survive
(the cutters' law, 2026-11-02). Every move is written to a review log first.

  python3 tools/m4_shelftidy.py [--bar 3] [--tops] [--roll] [--apply]
                                 [--dir D] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "serve")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from strata_control.datafolder import data_dir                     # noqa: E402
from serve.memory import MemoryService, class_name                 # noqa: E402

CANON = ("MEM", "OPS", "HW", "AI", "TECH", "DEC", "USR", "POL", "EVAL", "DOC", "STR",
         "FIC", "FILL", "SCI", "BIO", "PHYS", "HUM", "HEALTH")
TOPS_PROMPT = """A memory store keeps facts on shelves written `TOP` or `TOP/CUTTER`.
These TOPS were invented for one or two facts each and need a family:

{rows}

Give the SHORTEST list of new top categories that covers them (3 to 6 tops, each a
3-6 letter uppercase code, e.g. `SCI - science: biology, chemistry, physics, health`).
Every code must be a family a person would say out loud, and each invented top is
assigned to exactly one family.

ANSWER FIRST, THINK AFTER. Reply with these two sections and nothing before them:

FAMILIES:
<CODE> - <subject words>

ASSIGN:
<INVENTED> -> <CODE>
<INVENTED> -> <CODE>
... one line for EVERY invented code, in the list above ...
"""
ASSIGN = re.compile(r"^\s*[-*]?\s*([A-Z][A-Z0-9]{1,9})\s*-{1,2}>\s*([A-Z][A-Z0-9]{1,9})\b",
                    re.M)


def ask_box(prompt, url, max_tokens=700, timeout=180.0):
    body = json.dumps({"model": "strata", "temperature": 0.0, "max_tokens": max_tokens,
                       "messages": [{"role": "user",
                                     "content": "{REASON:off}\n\n" + prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310
        data = json.loads(resp.read().decode())
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    return str(msg.get("content") or msg.get("reasoning_content") or "")


def census(svc):
    with svc.lock:
        rows = svc.conn.execute(
            "select class, count(*) from memories where invalid_at is null"
            " and coalesce(scope,'') not like 'doc-%%' and coalesce(class,'')<>''"
            " group by 1").fetchall()
        svc.conn.commit()
    return {r[0]: int(r[1]) for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(data_dir(ROOT) / "memory-eval"))
    ap.add_argument("--bar", type=int, default=3, help="rows a cutter needs to earn its drawer")
    ap.add_argument("--tops", action="store_true", help="run the tops pass (needs the box)")
    ap.add_argument("--roll", action="store_true", help="run the 3-row-bar roll-up")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--url", default="http://127.0.0.1:8005/v1/chat/completions")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not (a.tops or a.roll):
        a.tops = a.roll = True

    svc = MemoryService(a.dir)
    shelves = census(svc)
    out = Path(a.out or str(data_dir(ROOT) / "bench" /
                            f"m4-shelftidy-{time.strftime('%Y-%m-%d')}.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"store: {sum(shelves.values()):,} classified rows on {len(shelves)} shelves; "
          f"bar {a.bar}; {'APPLY' if a.apply else 'dry run'}; log {out}")
    moved = Counter()

    with out.open("a", encoding="utf-8") as log:
        def post(old, new, kind):
            moved[kind] += 1
            log.write(json.dumps({"from": old, "to": new, "kind": kind,
                                  "rows": shelves.get(old, 0)}) + "\n")
            log.flush()
            if a.apply:
                with svc.lock:
                    svc.conn.execute("update memories set class=%s, updated_at=updated_at"
                                     " where invalid_at is null and class=%s"
                                     " and coalesce(scope,'') not like 'doc-%%'",
                                     (class_name(new), old))
                    svc.conn.commit()
                    svc._vdirty = True

        if a.tops:
            invented = sorted({c.split("/")[0] for c in shelves} - set(CANON))
            if invented:
                body = "\n".join(
                    f"{t} - {shelves.get(t,0)} row(s), e.g. "
                    + (svc.conn.execute("select text from memories where class=%s"
                                        " and invalid_at is null limit 1", (t,)).fetchone()
                      or ["?"])[0][:70]
                    for t in invented)
                ans = ask_box(TOPS_PROMPT.format(rows=body), a.url, max_tokens=1200)
                pairs = dict(ASSIGN.findall(ans))
                print(f"tops: {len(invented)} invented -> {len(set(pairs.values()))} families"
                      f" ({', '.join(sorted(set(pairs.values())))})")
                for cl, n in sorted(shelves.items()):
                    top = cl.split("/")[0]
                    if top in pairs and pairs[top] != top:
                        cut = cl.split("/")[1] if "/" in cl else pairs[top]
                        post(cl, f"{pairs[top]}/{cut}", "top")
            else:
                print("tops: nothing invented to place")
        if a.roll:
            n = 0
            for cl, cnt in sorted(shelves.items()):
                if "/" in cl and cnt < a.bar:
                    post(cl, cl.split("/")[0], "roll")
                    n += 1
            print(f"roll: {n} cutters under {a.bar} rows ride their family")
    print(f"moves: {dict(moved)}" + ("" if a.apply else "  (dry run - nothing written)"))
    svc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
