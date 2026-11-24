#!/usr/bin/env python3
"""m11_semantic.py — semantic edges for the repo graph, on the STORE's ruler (2026-11-24, the merge).

The repo graph (graphify-out/graph.json) is 184,727 nodes and 454,530 edges and every one of them
is structural: calls, imports, contains, defines, references (measured — 0 semantic edges). AST
knows that `search()` calls `_semantic()`; it does not know that a function in `serve/docs.py`
implements the same idea a paper describes. graphify 0.9.114 exposes no embedding pass (checked in
the installed package: no flag in cli.py or __main__.py), so this is our own.

One ruler, not two: the embedder is the store's `embeddinggemma-2` — the same model that made the
35,740 fact vectors — so a "similar" in the code graph means the same thing as a "similar" in the
store. Measured on this box: 116 labels/s at batch 16, 122 at batch 64, median label 21 chars, so
the whole graph is ~25 min and the vectors are 0.57 GB of float32.

The output is a SIDECAR, `graphify-out/semantic.json`, not an edit to graph.json: graphify owns its
file and rewrites it on every `--update` (the nightly 04:40 timer), so edges written into it would
vanish with the next AST pass. The sidecar carries the label fingerprint, so a re-run re-embeds
only the nodes whose label moved (item 15's law, applied to the graph).

    .venv/bin/python tools/m11_semantic.py                  # full pass
    .venv/bin/python tools/m11_semantic.py --update         # only what moved
    .venv/bin/python tools/m11_semantic.py --k 8 --threshold 0.82 --top 20000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np                                        # noqa: E402
from serve.embedder import create                         # noqa: E402
from strata_control.datafolder import data_dir            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent             # terminal/
OUT = ROOT.parent / "graphify-out"
CACHE = OUT / "cache"
VEC = CACHE / "labels.f32"
MANIFEST = CACHE / "labels.json"


def fingerprint(label: str) -> str:
    return hashlib.sha1(str(label).encode("utf-8")).hexdigest()[:12]


def load_nodes(graph_path: Path):
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = g.get("nodes") or []
    out = []
    for n in nodes:
        nid = str(n.get("id") or "")
        label = str(n.get("label") or nid)
        kind = str(n.get("type") or n.get("kind") or n.get("community") or "node")
        # The label alone is 21 characters of identifier; the kind is what makes a symbol
        # comparable to a concept ("search · function" sits nearer "recall · module" than
        # "search · test" does), and it is free.
        out.append((nid, f"{label} · {kind}", n.get("source_file") or "", fingerprint(label)))
    return out


def embed(nodes, model, batch=32, resume=True, log=print):
    """Embed every label, reusing the cache for labels whose fingerprint still matches."""
    CACHE.mkdir(parents=True, exist_ok=True)
    man = {}
    if resume and MANIFEST.exists():
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dims = model.dims
    have = {}
    if VEC.exists() and man:
        raw = np.frombuffer(VEC.read_bytes(), dtype=np.float32).reshape(-1, dims)
        for i, nid in enumerate(man.get("order") or []):
            have[nid] = raw[i]
    todo = [i for i, (nid, _lab, _src, fp) in enumerate(nodes)
            if man.get("fp", {}).get(nid) != fp]
    log(f"{len(nodes):,} nodes, {len(todo):,} labels to embed "
        f"({len(nodes) - len(todo):,} cached), batch {batch}")
    vecs = np.zeros((len(nodes), dims), dtype=np.float32)
    t0 = time.time()
    for i, (nid, _lab, _src, _fp) in enumerate(nodes):
        if nid in have:
            vecs[i] = have[nid]
    for start in range(0, len(todo), batch):
        idxs = todo[start:start + batch]
        vecs[idxs] = model.embed_docs([nodes[i][1] for i in idxs])
        done = min(start + batch, len(todo))
        if done % 8192 < batch:
            el = time.time() - t0
            log(f"  {done:,}/{len(todo):,} in {el:.0f}s "
                f"({done / max(el, .001):.0f}/s, {(len(todo) - done) / max(done / el, .001) / 60:.1f} min left)")
    VEC.write_bytes(vecs.astype(np.float32).tobytes())
    MANIFEST.write_text(json.dumps({"order": [n[0] for n in nodes],
                                    "fp": {n[0]: n[3] for n in nodes},
                                    "dims": dims,
                                    "model": getattr(model, "model_name", "embeddinggemma-2")}),
                        encoding="utf-8")
    log(f"embedded in {time.time() - t0:.0f}s → {VEC} ({VEC.stat().st_size / 1e9:.2f} GB)")
    return vecs


def knn(vecs, nodes, k=8, threshold=0.82, block=2048, log=print):
    """Blocked top-k cosine, self excluded. 184,727² is 137 GB of scores if you materialize it,
    so the pass runs in row blocks: one block's scores at a time, argpartition for the top-k."""
    n = vecs.shape[0]
    V = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    edges = []
    t0 = time.time()
    for start in range(0, n, block):
        stop = min(start + block, n)
        S = V[start:stop] @ V.T
        np.fill_diagonal(S[start:stop, start:stop], 0.0) if stop - start == n else None
        for r in range(S.shape[0]):
            row = S[r]
            kk = min(k, n - 1)
            cand = np.argpartition(-row, kk)[:kk]
            cand = cand[np.argsort(-row[cand])]
            gi = start + r
            for j in cand:
                j = int(j)
                if j == gi:
                    continue
                c = float(row[j])
                if c >= threshold:
                    a, b = (gi, j) if gi < j else (j, gi)
                    edges.append((a, b, round(c, 4)))
        if start % (block * 8) == 0:
            log(f"  knn {stop:,}/{n:,} in {time.time() - t0:.0f}s, {len(edges):,} edges so far")
    # one edge per unordered pair, the tighter cosine wins
    best = {}
    for a, b, c in edges:
        key = (a, b)
        if key not in best or c > best[key]:
            best[key] = c
    out = [{"source": nodes[a][0], "target": nodes[b][0], "cos": c,
            "relation": "semantically_similar_to", "confidence": "INFERRED",
            "confidence_score": c, "_origin": "embedding"}
           for (a, b), c in sorted(best.items(), key=lambda kv: -kv[1])]
    log(f"knn in {time.time() - t0:.0f}s: {len(out):,} unique pairs at cos >= {threshold}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graph", default=str(OUT / "graph.json"))
    ap.add_argument("--out", default=str(OUT / "semantic.json"))
    ap.add_argument("--model", default=str(data_dir(ROOT) / "embeddings/embeddinggemma-2"))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--threshold", type=float, default=0.82)
    ap.add_argument("--top", type=int, default=0, help="keep the N tightest pairs (0 = all)")
    ap.add_argument("--update", action="store_true", help="embed only labels whose fingerprint moved")
    a = ap.parse_args()
    t0 = time.time()
    nodes = load_nodes(Path(a.graph))
    model = create(a.model, threads=a.threads)
    vecs = embed(nodes, model, batch=a.batch, resume=True, log=lambda m: print(m, flush=True))
    edges = knn(vecs, nodes, k=a.k, threshold=a.threshold, log=lambda m: print(m, flush=True))
    if a.top:
        edges = edges[:a.top]
    Path(a.out).write_text(json.dumps({
        "generated": int(time.time()), "seconds": round(time.time() - t0, 1),
        "model": getattr(model, "model_name", "embeddinggemma-2"), "dims": model.dims,
        "k": a.k, "threshold": a.threshold, "nodes": len(nodes), "edges": len(edges),
        "note": "sidecar to graphify-out/graph.json, which graphify rewrites on --update; "
                "read this with the graph, not instead of it",
        "pairs": edges}, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out}: {len(edges):,} semantically_similar_to edges over {len(nodes):,} nodes "
          f"in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
