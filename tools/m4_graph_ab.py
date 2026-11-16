#!/usr/bin/env python3
"""m4_graph_ab.py — does the graph arm move recall? One measurement, two arms.

The arm (serve/memory.py `_graph_expand`) casts an RRF vote for the graph neighbours of the
rows the lexical and cosine arms already like, weighted by `memory.graph_weight`. That helps
exactly when a question shares words with one row of a cluster and the right answer is a
neighbour. It can cost exactly the same amount: a vote for a neighbour is a vote against
whatever it displaces.

So: take N live facts, ask each one's own opening words as a query — the gold row is the row
itself, no annotation needed — and record where it lands with the arm off and with the arm on.
Same queries, same store, same embedder, one variable.

    .venv/bin/python tools/m4_graph_ab.py --n 40 --weights 0,0.45

Reads: mean rank and top-8 hits per weight. The arm's cost is one dict load and one SELECT, so
the wall-clock difference is the model, not the graph.
"""
from __future__ import annotations

import argparse
import os
import statistics
import time

from serve.memory import MemoryService

STORE = os.environ.get("STRATA_STORE", "/home/eugene/Strata-data/memory-eval")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40, help="probes (live facts used as their own gold)")
    ap.add_argument("--weights", default="0,0.45", help="comma list of graph_weight arms")
    ap.add_argument("--limit", type=int, default=50, help="candidates per probe")
    ap.add_argument("--min-recalls", type=int, default=1, help="prefer facts the recall block has served")
    ap.add_argument("--set", default="linked", choices=("linked", "served"),
                    help="linked: probe a fact with the words of a graph NEIGHBOUR of it — the "
                         "case the arm exists for, a question phrased on one row whose answer "
                         "sits on the row linked to it. served: the facts recall already brings up.")
    a = ap.parse_args()

    base = MemoryService(STORE)
    if a.set == "linked":
        adj = base._graph()
        pairs = [(row_id, nb) for row_id, nbs in adj.items() for nb in nbs]
        rows = base.conn.execute(
            "SELECT id, text FROM memories WHERE id = ANY(%s) AND invalid_at IS NULL",
            ([*(  {p[0] for p in pairs} | {p[1] for p in pairs})],)).fetchall()
        text = {r[0]: (r[1] or "").strip() for r in rows}
        probes = []
        for row_id, nb in pairs:                       # ask with the neighbour's words
            q = " ".join(text.get(nb, "").split()[:12])
            if len(q) > 30 and text.get(row_id):
                probes.append((row_id, q))             # gold = the linked row
        probes = probes[:a.n]
    else:
        rows = base.conn.execute(
            "SELECT m.id, m.text FROM memories m JOIN embeddings e ON e.id = m.id "
            "WHERE m.invalid_at IS NULL AND m.source NOT LIKE 'doc-index%%' AND length(m.text) > 60 "
            "ORDER BY m.hits DESC, m.id DESC LIMIT %s", (a.n * 4,)).fetchall()
        probes = [(r[0], " ".join((r[1] or "").split()[:12])) for r in rows][:a.n]
    print(f"{len(probes)} {a.set} probes against {STORE}"
          + ("  (gold = the row the graph links to, query = a neighbour's words)"
             if a.set == "linked" else "  (gold = the row the query was cut from)"))

    for w in [float(x) for x in a.weights.split(",")]:
        svc = MemoryService(STORE, graph_weight=w)
        ranks, t0 = [], time.time()
        for rid, q in probes:
            hits = svc.search(q, limit=a.limit)
            order = [h["id"] for h in hits]
            ranks.append(order.index(rid) + 1 if rid in order else a.limit + 1)
        top8 = sum(1 for r in ranks if r <= 8)
        print(f"  graph_weight {w:<5}  mean rank {statistics.mean(ranks):6.2f}"
              f"  median {statistics.median(ranks):5.1f}"
              f"  top-8 {top8}/{len(ranks)}"
              f"  {time.time() - t0:5.1f}s")
        if w == 0.0:
            first = ranks
        else:
            moved = [(p[0], f, r) for p, f, r in zip(probes, first, ranks) if f != r]
            up = sum(1 for _, f, r in moved if r < f)
            print(f"      {len(moved)} probes moved: {up} up, {len(moved) - up} down")


if __name__ == "__main__":
    main()
