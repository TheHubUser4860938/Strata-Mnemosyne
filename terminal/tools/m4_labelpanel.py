#!/usr/bin/env python3
"""m4_labelpanel.py — the shelf clerk's labeling quality, measured (2026-11-24).

The clerk is the highest-leverage unmeasured step in the store: 90% of the active facts are
harvest-written, and the harvest files each new fact through `fact_class(...) or clerk_class(...)`
— the keyword map first, the served model when the map cannot name it. The only number on the
record for that model's stability was anecdotal and ugly: at temp 0.8 it moved the shelf between
two identical asks on 2 of 4 facts (filed 2026-11-03).

So: take the facts the keyword map cannot name — the clerk's real input, not a fixture — ask the
same question twice against the store's own shelf list, and report agreement. This is the panel
the Shelving module is tested through, and the falsifier for every clerk change that follows.

    PYTHONPATH=. .venv/bin/python tools/m4_labelpanel.py --n 40 [--temp 0.8] [--budget 1400]

Reads:
  AGREEMENT  the share of facts where the clerk names the same shelf both times
  WILD       the share where it named nothing (a shrug is a legal answer: wild rides every ask)
  new-cutter the share that named a shelf the store does not hold yet (25 tops came from this)
  where      the shelf distribution it chose

THE DOOR, NOT A SECOND STORE: the facts come through the server's own `/memory` API. An
in-process `MemoryService(dir)` opens its own connection to the embedded cluster, and every
cluster on this box listens on port 5432, distinguished only by its unix-socket directory — so
with the serve suite running (it spins up `/tmp/strata-test-pg-*` clusters) a probe can be
answered by a cluster whose database is empty and measure nothing. Measured the hard way on
2026-11-24: the first run of this panel sampled 0 facts and reported AGREEMENT 0/1.

It runs the SHIPPED path: `curate_loop.clerk_class` with the same 1,400-token budget the harvest
uses, against the shelf list the store itself holds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))     # terminal/ on the path
from curate_loop import clerk_class                                  # noqa: E402

URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8005")


def post(op_body, timeout=180):
    req = urllib.request.Request(URL + "/memory", data=json.dumps(op_body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ask_factory(model: str, temp: float):
    def ask(text, maxtok, want_geom=None, kind=""):
        body = {"model": model,
                "messages": [{"role": "user", "content": "{REASON:off}\n\n" + text}],
                "temperature": temp, "reasoning_effort": "off",
                "max_tokens": maxtok, "stream": False}
        req = urllib.request.Request(URL + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "X-Strata-Memory": "off"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.load(r)
        except Exception:                                        # noqa: BLE001 - a shrug, not a crash
            return None, None, False
        c = (d.get("choices") or [{}])[0]
        return ((c.get("message") or {}).get("content") or "").strip(), \
            (c.get("usage") or {}).get("prompt_tokens"), want_geom is None
    return ask


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--temp", type=float, default=0.8, help="the temperature the harvest runs at")
    ap.add_argument("--budget", type=int, default=1400, help="the clerk's own token budget")
    ap.add_argument("--scope", default="default")
    ap.add_argument("--seed", type=int, default=7, help="the sample is reproducible")
    ap.add_argument("--pool", type=int, default=400,
                    help="rows to pull through the door before sampling")
    a = ap.parse_args()

    model = json.load(urllib.request.urlopen(URL + "/health", timeout=30)).get("model", "strata")
    got = post({"op": "search", "q": "the", "limit": a.pool, "scope": a.scope})
    res = got.get("result") or got            # the door answers {ok, result:{hits}}, and mirrors
    rows = res.get("hits") or got.get("hits") or []     # hits at the top — read both, as it ships
    facts = [(r["id"], (r.get("text") or "").strip(), r.get("class") or "", r.get("source") or "")
             for r in rows if len((r.get("text") or "").strip()) > 40]
    facts.sort(key=lambda r: hashlib.md5(f"{r[0]}:{a.seed}".encode()).hexdigest())
    # THE FRAME: the clerk is asked about a fact the KEYWORDS could not name, so the population it
    # works on is the harvest's own output — every row whose source is a curation date. Wild rows
    # today are the residue the clerk FAILED to place; sampling only those measures its shrug, not
    # its judgment. Both numbers are printed: agreement on the harvest's text, and the shelf it
    # chose, which is the thing 90% of the store's facts carry.
    harvested = [r for r in facts if r[3].startswith("curation")]
    sample = harvested[:a.n]
    if not sample:
        print(f"no harvested facts in the {len(facts)} rows the door returned "
              f"(--pool {a.pool}); widen the pool or ask a broader q.")
        return
    print(f"{len(sample)} harvest-written facts drawn from {len(facts)} rows the server returned — "
          f"the clerk's real input")
    print(f"model {model} · temp {a.temp} · budget {a.budget} · shelf list from the live store\n")
    ask = ask_factory(model, a.temp)

    have = {r.get("class") for r in rows if r.get("class")}
    agree = named = cutter = 0
    shelves = Counter()
    detail = []
    for rid, text, _klass, _src in sample:      # 4-tuple: the source names the frame
        one = clerk_class(text, ask)          # the shipped call, the shipped budget
        two = clerk_class(text, ask)          # the same question again
        same = (one or "") == (two or "")
        agree += same
        named += bool(one)
        cutter += bool(one and one not in have)
        shelves[one or "WILD"] += 1
        detail.append({"id": rid, "first": one, "second": two, "same": same,
                       "fact": text[:120]})
        print(f"  {'=' if same else '≠'}  {(one or 'WILD'):<16} {(two or 'WILD'):<16} {text[:66]}")

    n = len(sample)
    print(f"\nAGREEMENT {agree}/{n} = {agree/n:.2f}   WILD {n-named}/{n} = {(n-named)/n:.2f}"
          f"   new-cutter {cutter}/{n} = {cutter/n:.2f}")
    print("where it files: " + ", ".join(f"{k}×{v}" for k, v in shelves.most_common(10)))
    out = Path(os.environ.get("STRATA_BENCH", "/home/eugene/Strata-data/bench")) / "p1"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"labelpanel-{date.today().isoformat()}.jsonl").write_text(
        "\n".join(json.dumps(d) for d in detail) + "\n", encoding="utf-8")
    print(f"rows → {out}/labelpanel-{date.today().isoformat()}.jsonl")


if __name__ == "__main__":
    main()
