#!/usr/bin/env python3
"""BM25 with field weights, scored against the founding shelf — before and after.

Why: the shelf's lexical arm ranks by Postgres ts_rank_cd, which has no idf and
no field weights. On the frozen 12-topic panel it lands PAPER 4/12 (journal,
2026-11-03). The same lever exists on the harness side (Clio build/lib/bm25.mjs,
step E3, receipt EVOLV internal/genome/search.go:57-70): a heading is worth more
than body prose, and a rare term is worth more than a common one.

What this measures, honestly:
  arm A  the store's own ranking, as op=search answers it (ts_rank_cd + vector)
  arm B  BM25 re-ranking the SAME candidate set, with the row's heading weighted
         above its body and the file name between them
So the number is a RE-RANK gain over the store's 20 candidates, not a
whole-corpus retrieval claim. The candidate set is fixed across arms, so the only
variable is the scorer.

Panel: 12 Federalist topics, gold = the paper the passage is in. A row's paper is
read out of its own text, because the sections index opens every row with its
heading ("FEDERALIST No. 10"), and the heading is the provenance that travels.

Run: .venv/bin/python tools/m4_bm25_eval.py [--limit 20] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from collections import Counter

URL = "http://127.0.0.1:8005/memory"
SCOPE = "doc-founding"

# field weights, EVOLV's shape (search.go:57-70) with the doc row's own fields
WEIGHTS = {"heading": 3.0, "file": 1.5, "body": 1.0}
PARAMS = {"k1": 1.2, "b": 0.75}

STOP = set(
    "a about above after again against all am an and any are as at be because been before being below between both "
    "but by can did do does doing down during each few for from further had has have having he her here hers herself "
    "him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only "
    "or other our ours ourselves out over own same she should so some such than the that their theirs them themselves "
    "then there these they this those through to too under until up very was we were what when where which while who "
    "whom why with would you your yours yourself yourselves".split()
)

# the frozen panel: (query, gold paper)
PANEL = [
    ("factions majority tyranny the rights of the people", 10),
    ("ambition must be made to counteract ambition checks and balances", 51),
    ("energy in the executive unity of the executive", 70),
    ("the judiciary the least dangerous branch life tenure", 78),
    ("the utility of the union to your prosperity commerce", 14),
    ("reflection and choice the Greek and Roman statesmen", 9),
    ("the difficulty of framing a system by reflection and choice", 1),
    ("standing armies in time of peace the effects of internal war", 8),
    ("the house of representatives frequency of election", 57),
    ("the treaty power the senate a check upon the president", 75),
    ("a mixed government part national part federal", 39),
    ("the powers reserved to the members of the confederacy", 45),
]

# the sections index writes the paper into provenance.section ("FEDERALIST No. 10"),
# and the heading also opens the row text; both are read, section first.
SECTION = re.compile(r"No\.?\s*([IVXLCivxlc]+|\d+)\s*$")
ROMAN_VALUES = (("lxxx", 80), ("lxx", 70), ("lx", 60), ("l", 50), ("xl", 40), ("xxx", 30), ("xx", 20),
                ("ix", 9), ("viii", 8), ("vii", 7), ("vi", 6), ("iv", 4), ("ix", 9), ("x", 10), ("v", 5),
                ("i", 1))


def roman_to_int(s: str) -> int | None:
    """A general small-roman parser: the Federalist papers run I..XLV plus a few."""
    t = s.lower()
    if t.isdigit():
        return int(t)
    n = 0
    i = 0
    pairs = [("xc", 90), ("lxxx", 80), ("lxx", 70), ("lx", 60), ("l", 50), ("xl", 40), ("xxx", 30),
             ("xx", 20), ("xix", 19), ("xviii", 18), ("xvii", 17), ("xvi", 16), ("xv", 15), ("xiv", 14),
             ("xiii", 13), ("xii", 12), ("xi", 11), ("ix", 9), ("viii", 8), ("vii", 7), ("vi", 6),
             ("iv", 4), ("x", 10), ("v", 5), ("i", 1)]
    while i < len(t):
        for sym, val in pairs:
            if t.startswith(sym, i):
                n += val
                i += len(sym)
                break
        else:
            return None
    return n or None


def post(body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def section_of(row: dict) -> str:
    return str((row.get("provenance") or {}).get("section") or "").strip()


def paper_of(row: dict) -> int | None:
    """The paper number, read out of the section the index wrote, then the heading."""
    sec = section_of(row)
    m = SECTION.search(sec) if sec else None
    if m:
        return roman_to_int(m.group(1))
    first = str(row.get("text") or "").split("\n", 1)[0].strip()
    m = SECTION.search(first)
    return roman_to_int(m.group(1)) if m else None


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(w) >= 2 and w not in STOP]


def bm25(cands: list[dict], query: str) -> list[dict]:
    """Rank the candidate set. tf carries the field weight; idf is the shelf's gap."""
    docs = []
    df: Counter = Counter()
    total = 0.0
    for c in cands:
        tf: Counter = Counter()
        length = 0.0
        for field, weight in (("heading", WEIGHTS["heading"]), ("file", WEIGHTS["file"]), ("body", WEIGHTS["body"])):
            text = section_of(c) if field == "heading" else (str((c.get("provenance") or {}).get("file") or "") if field == "file" else str(c.get("text") or ""))
            for w in words(text):
                tf[w] += weight
                length += 1.0
        length = length or 1.0
        total += length
        for w in tf:
            df[w] += 1
        docs.append({"row": c, "tf": tf, "len": length})
    n = len(docs) or 1
    avgdl = max(1.0, total / n)
    terms = words(query)
    scored = []
    for d in docs:
        s = 0.0
        for t in set(terms):
            f = d["tf"].get(t, 0)
            if f <= 0:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            idf = max(0.1, idf)
            k1, b = PARAMS["k1"], PARAMS["b"]
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (d["len"] / avgdl)))
        if s > 0:
            scored.append((s, d["row"]))
    scored.sort(key=lambda p: -p[0])
    return [r for _, r in scored]


def mrr(ranked: list[dict], gold: int) -> float:
    for i, row in enumerate(ranked, 1):
        if paper_of(row) == gold:
            return 1.0 / i
    return 0.0


def top_paper(ranked: list[dict]) -> int | None:
    return paper_of(ranked[0]) if ranked else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="candidates fetched per query")
    ap.add_argument("--json", default="", help="write the per-query records here")
    a = ap.parse_args()

    rows = []
    for query, gold in PANEL:
        res = post({"op": "search", "q": query, "limit": a.limit, "scope": SCOPE})
        cands = res.get("hits") or []
        arm_a = cands
        arm_b = bm25(cands, query)
        rows.append({
            "query": query, "gold": gold, "n": len(cands),
            "a_top": top_paper(arm_a), "a_mrr": mrr(arm_a, gold),
            "b_top": top_paper(arm_b), "b_mrr": mrr(arm_b, gold),
        })

    def rate(key):
        return sum(1 for r in rows if r[key] == r["gold"])
    def mean(key):
        return round(sum(r[key] for r in rows) / len(rows), 3) if rows else 0.0

    print(f"panel: {len(rows)} topics  candidates/query={a.limit}  scope={SCOPE}")
    print(f"  A shelf lexical+vector  PAPER@1={rate('a_top')}/{len(rows)}  MRR={mean('a_mrr')}")
    print(f"  B BM25 field-weighted   PAPER@1={rate('b_top')}/{len(rows)}  MRR={mean('b_mrr')}")
    print()
    for r in rows:
        flip = ""
        if r["a_top"] != r["gold"] and r["b_top"] == r["gold"]:
            flip = "  <- BM25 wins"
        elif r["a_top"] == r["gold"] and r["b_top"] != r["gold"]:
            flip = "  <- BM25 loses"
        print(f"  Fed {r['gold']:>3}  A={str(r['a_top']):>4}  B={str(r['b_top']):>4}  mrr A={r['a_mrr']:.2f} B={r['b_mrr']:.2f}{flip}")
    print("\nreading: PAPER@1 asks whether the top row's provenance.section names the gold")
    print("paper. A row from a volume with no section (Adams's letters, Hamilton's works)")
    print("scores nothing under either arm, so this is the Federalist-file binding, measured.")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
        print(f"records -> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
