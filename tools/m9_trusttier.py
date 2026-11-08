#!/usr/bin/env python3
"""Measure the trust tier: what does demoting DERIVED facts do to recall, on the store's own labels?

The idea is borrowed from mnemosyne-oss/mnemosyne, read in `mnemosyne/core/beam.py` on 2026-11-08:
ingestion source sets a TRUST TIER (STATED / IMPORTED / EXTERNAL_WRITE / DERIVED) and consolidation
summaries rank at 0.25x "so they don't enter ranking at the same weight as the sources they
paraphrase". We already tag the harvest's rows (`source = curation-<date>`, tools/curate_loop.py) and
never weighted them, so a tidy paraphrase can beat the sentence it came from.

The knob is `MemoryService(derived_weight=d)`: d=1.0 is today's bytes, 0<d<1 multiplies a derived
row's score AFTER fusion and BEFORE the exposure decay. Nothing is filtered (see serve/memory.py
_trust_tier), so the block's score floor stays the only cut.

The panel is the store's OWN labels, which is why no new gold file is needed: 1,768 active rows carry
`provenance.probe` (a question) and `provenance.gold` (the answer) and are the row that holds both,
so a recall that returns that row for that probe is a hit. Sampled stratified by shelf, frozen seed.

Two panels, because the tier has two audiences:
  FACTS  the probe rows (all of them derived) - the demote is a headwind here, and the number says how strong
  DOCS   the frozen 12-topic founding panel (all stated) - the demote is a tailwind here

    .venv/bin/python tools/m9_trusttier.py [--n 150] [--weights 1.0,0.5,0.25] [--arms lexical,fused]

Read the SHAPE, not the mean: the pair of numbers that matters is (facts top-1) against (docs top-1).
If the demote costs the facts panel and buys the docs panel, the tier is a real trade; if it moves
both the same way, the label is doing nothing and the knob is decoration.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path.home() / "Projects/Strata-Mnemosyne"
sys.path[:0] = [str(ROOT), str(ROOT / "serve")]
from serve.embedder import create as create_embedder            # noqa: E402
from serve.memory import MemoryService                          # noqa: E402

STORE = str(Path.home() / "Strata-data/memory-eval")
EMBEDDER = str(Path.home() / "Strata-data/embeddings/embeddinggemma-2")
SEED = 20261108                     # frozen: a panel that re-samples every run measures the sampler
# The founding panel's 12 topics, verbatim from bench/p1/docs_paper_eval.py (the same queries the
# PAPER/SHELF/FILE numbers are filed against, so a trust-tier move there is comparable to that series).
TOPIC = {10: ["faction", "sphere"], 14: ["confederacy", "extency"], 37: ["obscurity", "certainty"],
         39: ["national", "federal"], 51: ["concentration", "department"],
         55: ["census", "representation"], 62: ["senate", "rotation"], 63: ["exclusion", "executive"],
         70: ["energy", "unity"], 78: ["judiciary", "sword"], 79: ["commissions", "behaviour"],
         84: ["bill", "appendix"]}
TOPIC[14] = ["confederacy", "extensive"]        # the filed pair (typo above is the kind a probe finds)


def probe_panel(conn, n: int) -> list[tuple[int, str, str]]:
    """(row id, probe, shelf) for a stratified sample of the store's labeled probes: one row per
    probe, taken evenly across shelves so MEM's bulk cannot outvote a 12-row drawer."""
    rows = conn.execute(
        "select id, provenance->>'probe', coalesce(class,'') from memories"
        " where invalid_at is null and provenance ? 'probe' and provenance ? 'gold'"
        "   and coalesce(provenance->>'probe','') <> '' order by id").fetchall()
    by: dict[str, list] = defaultdict(list)
    for rid, probe, cls in rows:
        by[cls.split("/")[0] or "(none)"].append((rid, probe, cls))
    fams = sorted(by, key=lambda k: (-len(by[k]), k))
    pick, i = [], 0
    per = max(1, n // max(1, len(fams)))
    while len(pick) < n and any(by.values()):
        fam = fams[i % len(fams)]
        if by[fam]:
            pick.append(by[fam].pop(random.Random(SEED + i).randrange(len(by[fam]))))
        i += 1
        if i > 40 * n:
            break
    return pick[:n]


def score(hits: list[dict], gold: int, k: int) -> dict:
    """One query's shape: did the gold row land, where, and how much of the top-k is derived?"""
    ids = [h["id"] for h in hits[:k]]
    rr = 1.0 / (ids.index(gold) + 1) if gold in ids else 0.0
    top = hits[:k]
    return {"hit": gold in ids, "rr": rr, "rank": (ids.index(gold) + 1) if gold in ids else None,
            "derived_share": sum(1 for h in top if h.get("derived")) / max(1, len(top)),
            "ids": ids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150, help="probes to sample (frozen seed)")
    ap.add_argument("--k", type=int, default=3, help="the window a block actually shows")
    ap.add_argument("--weights", default="1.0,0.5,0.25")
    ap.add_argument("--arms", default="lexical,fused")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    weights = [float(w) for w in a.weights.split(",")]
    arms = [x.strip() for x in a.arms.split(",")]

    emb = create_embedder(EMBEDDER)
    mem = MemoryService(STORE, embedder=emb)
    probes = probe_panel(mem.conn, a.n)
    docs = [(no, " ".join(w)) for no, w in sorted(TOPIC.items())]
    print(f"[tier] store {mem.stats()['memories']} active rows; facts panel n={len(probes)}"
          f" (seed {SEED}), docs panel n={len(docs)}, k={a.k}, weights={weights}, arms={arms}",
          flush=True)

    rep: dict = {"n_probes": len(probes), "k": a.k, "seed": SEED, "store": mem.stats()["memories"],
                 "arms": {}, "notes": "facts golds are all derived rows (source curation-*); "
                                      "docs rows are all stated (source doc-index-N)"}
    for arm in arms:
        sem = arm == "fused"
        base: dict[int, list[int]] = {}
        for w in weights:
            mem.derived_weight = min(1.0, max(0.0, w))
            f = {"top1": 0, "topk": 0, "mrr": 0.0, "dshare": 0.0, "moved": 0}
            t0 = time.time()
            for rid, probe, _cls in probes:
                hits = mem.search(probe, limit=max(10, a.k * 3), semantic=sem)
                s = score(hits, rid, a.k)
                f["top1"] += bool(hits) and hits[0]["id"] == rid
                f["topk"] += s["hit"]
                f["mrr"] += s["rr"]
                f["dshare"] += s["derived_share"]
                if w == weights[0]:
                    base[rid] = s["ids"]
                elif s["ids"] != base.get(rid):
                    f["moved"] += 1
            d = {"top1": round(f["top1"] / len(probes), 3),
                 f"top{a.k}": round(f["topk"] / len(probes), 3),
                 "mrr": round(f["mrr"] / len(probes), 3),
                 "derived_share_topk": round(f["dshare"] / len(probes), 3),
                 "topk_changed_vs_1.0": f["moved"],
                 "sec": round(time.time() - t0, 1)}
            # the docs panel at the same weight: the tailwind side of the same knob
            g = {"top1": 0, "dshare": 0.0, "rows": []}
            for no, q in docs:
                hits = mem.search(q, limit=max(10, a.k * 3), semantic=sem)
                g["top1"] += bool(hits) and not hits[0].get("derived")   # a stated row on top
                g["dshare"] += (sum(1 for h in hits[:a.k] if h.get("derived")) / a.k)
                g["rows"].append({"paper": no, "top": (hits[0].get("class") if hits else None),
                                  "derived": bool(hits and hits[0].get("derived"))})
            rep["arms"][f"{arm}@{w}"] = {"facts": d,
                                         "docs_stated_top1": round(g["top1"] / len(docs), 3),
                                         "docs_derived_share_topk": round(g["dshare"] / len(docs), 3)}
            print(f"[tier] {arm:8s} w={w:<5} facts top1={d['top1']:.3f} "
                  f"top{a.k}={d[f'top{a.k}']:.3f} mrr={d['mrr']:.3f} "
                  f"derived-share={d['derived_share_topk']:.3f} moved={d['topk_changed_vs_1.0']:3d}"
                  f"   docs stated-top1={rep['arms'][f'{arm}@{w}']['docs_stated_top1']:.3f}"
                  f"  ({d['sec']}s)", flush=True)
    dest = Path(a.out) if a.out else (Path.home() /
                                      "Strata-data/bench/p1/trusttier-2026-11-08.json")
    dest.write_text(json.dumps(rep, indent=1))
    print(f"[tier] record: {dest}")
    mem.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
