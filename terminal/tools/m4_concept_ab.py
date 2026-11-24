#!/usr/bin/env python3
"""m4_concept_ab.py — does walking the concept nodes pay? Fixed probes, swept fan.

The graph arm votes on a row's graph neighbours. Until 2026-11-24 it saw only the edges that join
two ROWS (`<shelf>_fact_<id>` on both ends), so 1,020 of the store graph's 3,133 edges reached the
ranking and the 1,913 concept nodes were dead ends. The walk makes a fact that shares a concept with
another fact a neighbour, capped per row at CONCEPT_FAN, ordered so a tight concept outsells a hub
and a direct edge outsells both.

`m4_graph_ab.py` builds its probes FROM the adjacency, so sweeping the fan sweeps the probe set and
the two arms stop being comparable. This harness fixes the probes at the walk's full neighbourhood
(fan 12) and then varies only the fan the arm sees — one variable, per the measurement law.

Gold = the row the graph links to; the query is a NEIGHBOUR's opening words. That is the case the
arm exists for: a question phrased on one row whose answer sits on the row linked to it.

    PYTHONPATH=. .venv/bin/python tools/m4_concept_ab.py --n 200 --fans 0,2,4,12 --weight 0.45

Reads: top-8 and mean rank per fan, and the moves against the arm-off baseline at the same probes.
Deterministic — no engine, no judge — so one run is the sample; the sample is the probes.
"""
from __future__ import annotations

import argparse
import os
import statistics

import serve.memory as M
from serve.memory import MemoryService

STORE = os.environ.get("STRATA_STORE", "/home/eugene/Strata-data/memory-eval")
PROBE_FAN = 12          # the neighbourhood the probes are cut from: the widest walk


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--fans", default="0,2,4,12")
    ap.add_argument("--weight", type=float, default=0.45)
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()

    M.CONCEPT_FAN = PROBE_FAN                      # probes: the full walk, fixed for every arm
    base = MemoryService(STORE)
    adj = base._graph()
    pairs = [(rid, nb) for rid, nbs in adj.items() for nb in nbs]
    text = {r[0]: (r[1] or "").strip() for r in base.conn.execute(
        "SELECT id, text FROM memories WHERE id = ANY(%s) AND invalid_at IS NULL",
        (list({p[0] for p in pairs} | {p[1] for p in pairs}),)).fetchall()}
    probes, seen = [], set()
    for rid, nb in pairs:
        q = " ".join(text.get(nb, "").split()[:12])
        if len(q) > 30 and text.get(rid) and (rid, q) not in seen:
            seen.add((rid, q))
            probes.append((rid, q))
    probes = probes[:a.n]
    direct = sum(1 for rid, q in probes
                 if text.get(rid) and q.split()[:6] == text[rid].split()[:6])
    print(f"{len(probes)} fixed probes (gold = a graph neighbour's row; query = the neighbour's "
          f"words)\n  probes cut through the walk at fan {PROBE_FAN}; ~{direct} share their "
          f"opening words with the gold row")

    M.CONCEPT_FAN = PROBE_FAN
    svc = MemoryService(STORE, graph_weight=0.0)
    first = []
    for rid, q in probes:
        order = [h["id"] for h in svc.search(q, limit=a.limit)]
        first.append(order.index(rid) + 1 if rid in order else a.limit + 1)
    print(f"  arm off           top-8 {sum(1 for r in first if r <= 8):3d}/{len(probes)}"
          f"  mean {statistics.mean(first):6.2f}  median {statistics.median(first):5.1f}")

    for spec in a.fans.split(","):
        fan = int(spec)
        M.CONCEPT_FAN = fan                        # the one variable
        svc = MemoryService(STORE, graph_weight=a.weight)
        ranks = []
        for rid, q in probes:
            order = [h["id"] for h in svc.search(q, limit=a.limit)]
            ranks.append(order.index(rid) + 1 if rid in order else a.limit + 1)
        moved = [(f, r) for f, r in zip(first, ranks) if f != r]
        up = sum(1 for f, r in moved if r < f)
        print(f"  fan {fan:<3} w {a.weight}   top-8 {sum(1 for r in ranks if r <= 8):3d}/{len(probes)}"
              f"  mean {statistics.mean(ranks):6.2f}  median {statistics.median(ranks):5.1f}"
              f"  moved {len(moved):3d}  {up} up / {len(moved) - up} down")
    base.close()
    svc.close()


if __name__ == "__main__":
    main()
