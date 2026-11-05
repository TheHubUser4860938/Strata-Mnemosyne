#!/usr/bin/env python3
"""B4 — measure the cache-parity fork against a non-parity call on one panel (2026-11-05).

Arm FRESH : a plain POST /v1/chat/completions; the standing texts ride as text.
Arm GRAFT : the same request with X-Strata-Carts-Graft: <cart>; the engine stages the
            cart's saved STATE (GRAFTED t b ms on its wire) and reads the prompt's head
            from cache. Hermes' shape: the fork's prefix is the parent's, byte-identical.

Reads the server's own usage.prompt_tokens (the field is the engine's charge for the
whole prompt — the field-name law; the cache saving shows in ms, not tokens) and the
engine's GRAFTED line in its log for the staged tokens.

  .venv/bin/python bench/p1/cart_parity_measure.py --out bench/p1/cart-parity-2026-11-05.jsonl
"""
import argparse
import json
import statistics
import time
import urllib.request

URL = "http://127.0.0.1:8005/v1/chat/completions"
PANEL = [
    "Name the three working words the Mnemosyne family grew from, in one line.",
    "One sentence: what does the field `tokens` on a cart row actually count?",
    "Which port does this box's Strata serve on?",
    "Quote the house rule about corrected rows, exactly five words if you can.",
    "What engine version is serving right now?",
    "In one clause: why is a skill description context load?",
]


def ask(q, graft=None, max_tokens=24):
    body = {"model": "swift", "messages": [{"role": "user", "content": q}],
            "max_tokens": max_tokens, "temperature": 0, "stream": False}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    if graft:
        req.add_header("X-Strata-Carts-Graft", graft)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.load(r)
    ms = (time.perf_counter() - t0) * 1000
    u = out.get("usage") or {}
    return {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "ms": round(ms), "answer": (out.get("choices") or [{}])[0].get("message", {}).get("content", "")[:120]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--graft", default="standing")
    ap.add_argument("--out", default="bench/p1/cart-parity.jsonl")
    a = ap.parse_args()
    rows = []
    with open(a.out, "w") as fh:
        for rep in range(a.repeats):
            for arm, graft in (("fresh", None), ("graft", a.graft)):
                for qi, q in enumerate(PANEL):
                    r = ask(q, graft=graft)
                    r.update(arm=arm, rep=rep, q=qi, graft_name=graft or "")
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
                    rows.append(r)
                    print(f"{arm:6s} rep{rep} q{qi}: ptok={r['prompt_tokens']} {r['ms']}ms :: {r['answer'][:48]!r}", flush=True)
    for arm in ("fresh", "graft"):
        sub = [r for r in rows if r["arm"] == arm]
        ms = [r["ms"] for r in sub]
        pt = [r["prompt_tokens"] for r in sub]
        print(f"{arm:6s} n={len(sub)} mean_ms={statistics.mean(ms):.0f} median_ms={statistics.median(ms):.0f} "
              f"mean_ptok={statistics.mean(pt):.0f}")
    f = [r["ms"] for r in rows if r["arm"] == "fresh"]
    g = [r["ms"] for r in rows if r["arm"] == "graft"]
    print(f"delta median ms (graft - fresh): {statistics.median(g) - statistics.median(f):+.0f}")


if __name__ == "__main__":
    main()
