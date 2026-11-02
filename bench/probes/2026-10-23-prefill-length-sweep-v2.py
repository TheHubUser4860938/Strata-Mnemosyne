#!/usr/bin/env python3
"""Prefill length sweep v2 - close in on real token targets with real prose.

v2/bench/probes/2026-10-23-prefill-length-sweep.py used a 48-word list, and this
model's tokenizer merges the repetition: a prompt sized for 131,072 tokens came back
as 27,435. So v2 never measured above 27K tokens. This version takes real English
prose out of the repo's own docs and closes in on each target: it sends, reads the
engine's own prompt_tokens, and adjusts the word count, up to --tries times. It stops
sizing by guesswork and starts reporting measured lengths.

Why it matters: the unlock doubles tensor-core fp16/bf16 mma with fp32 accumulate, and
in this engine that instruction is in the prompt attention kernel
(src/kernels/cuda/qsa_prompt_attn.cu) alone. The test is the SHAPE of the curve:
  - prompt tok/s RISING with length  -> a fixed per-request cost dominates, attention
    is not the work, so doubling attention throughput changes little.
  - prompt tok/s FALLING with length -> attention is a real and growing slice, and the
    unlock has somewhere to bite.

Against the server already running (default http://127.0.0.1:8005). Speed only.
temperature 0, thinking off, fresh unique tag per request so the conversation cache
cannot help. Reads the engine's own timings (prompt_ms, prompt_per_second).

Usage: python3 bench/probes/2026-10-23-prefill-length-sweep-v2.py [--sizes
16384,65536,131072] [--runs 2] [--source docs/DETAILS.md] [--tol 0.05]
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def chat(base: str, key: str, messages: list, max_tokens: int, timeout: float) -> dict:
    body = {
        "model": "strata",
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": messages,
    }
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-type": "application/json"} | ({"Authorization": "Bearer " + key} if key else {}),
    )
    first, usage, timings, err = None, None, None, None
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    j = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = "".join(c.get("delta", {}).get("content") or "" for c in (j.get("choices") or []))
                if first is None and delta:
                    first = time.perf_counter() - start
                if j.get("usage"):
                    usage = j["usage"]
                if j.get("timings"):
                    timings = j["timings"]
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    return {"first": first, "total": time.perf_counter() - start, "usage": usage,
            "timings": timings, "err": err}


def prose(source: Path, rng: random.Random) -> list[str]:
    """Sentences of real repo prose, long enough to build any prompt we need."""
    text = source.read_text(encoding="utf-8", errors="replace")
    words = [w for w in text.split() if w.isalpha() and len(w) > 2]
    pool = words[:20000] or words
    rng.shuffle(pool)
    return pool


def build(pool: list[str], words: int, tag: str) -> str:
    rng = random.Random(tag)
    out, i = [], 0
    while i < words:
        take = min(24, words - i)
        chunk = rng.sample(pool, take) if take <= len(pool) else pool[:take]
        out.append(" ".join(chunk))
        i += take
    return f"UNLOCK-SWEEP {tag} || " + " ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8005")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--sizes", default="16384,32768,65536,131072")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--tries", type=int, default=4)
    ap.add_argument("--tol", type=float, default=0.05)
    ap.add_argument("--max-new", type=int, default=24)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--source", default="docs/DETAILS.md")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    source = (REPO / args.source) if not Path(args.source).is_absolute() else Path(args.source)
    pool = prose(source, random.Random("pool"))
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    tpw = 1.4  # starting guess, tokens per word; corrected per size from the engine's own count
    rows: list[dict] = []
    print(f"# prefill length sweep v2 against {base}  {date.today().isoformat()}\n"
          f"# prose pool: {source.name}, {len(pool)} real words; targets {sizes}", flush=True)

    for target in sizes:
        words = int(target / tpw)
        measured = None
        for attempt in range(args.tries):
            probe = chat(base, args.api_key, [{"role": "user", "content": build(pool, words, f"T{target}a{attempt}")}],
                         args.max_new, args.timeout)
            measured = (probe.get("usage") or {}).get("prompt_tokens")
            if probe["err"] or not measured:
                print(f"  size {target}: probe failed {probe['err']}", flush=True)
                measured = None
                break
            tpw = measured / words
            if abs(measured - target) / target <= args.tol:
                break
            words = max(1, int(target / tpw))
        if not measured:
            print(f"  size {target}: giving up", flush=True)
            continue
        print(f"  size {target}: sized at {words} words -> measured {measured} tokens "
              f"({tpw:.3f} tok/word), now {args.runs} timed runs", flush=True)

        for run in range(args.runs):
            tag = f"S{measured}-{run}-{int(time.time()) % 100000}"
            r = chat(base, args.api_key, [{"role": "user", "content": build(pool, words, tag)}],
                     args.max_new, args.timeout)
            u, t = r.get("usage") or {}, r.get("timings") or {}
            row = {"target": target, "run": run, "prompt_tokens": u.get("prompt_tokens"),
                   "prompt_ms": t.get("prompt_ms"), "prompt_tps": t.get("prompt_per_second"),
                   "ttft_s": round(r["first"], 3) if r["first"] else None, "err": r["err"]}
            rows.append(row)
            print(f"    {row['prompt_tokens']:>7} tokens: {row['prompt_ms']}ms "
                  f"{row['prompt_tps']} tok/s ttft={row['ttft_s']}s "
                  f"{'ERR ' + str(row['err']) if row['err'] else ''}", flush=True)

    out = args.out or f"bench/probes/{date.today().isoformat()}-prefill-length-sweep-v2.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"base": base, "date": date.today().isoformat(),
                                     "source": str(source), "rows": rows}, indent=2))
    print(f"wrote {out}", flush=True)

    good = sorted((r for r in rows if r["prompt_tps"] and r["prompt_tokens"]), key=lambda r: r["prompt_tokens"])
    if len(good) >= 2:
        print("\n# marginal cost of added tokens (a rising number means attention is growing work):", flush=True)
        for a, b in zip(good, good[1:]):
            ta = 1000 * a["prompt_tokens"] / a["prompt_tps"] / 1000
            tb = 1000 * b["prompt_tokens"] / b["prompt_tps"] / 1000
            dn = (b["prompt_tokens"] - a["prompt_tokens"]) / 1000
            if dn >= 0.5:
                print(f"  {a['prompt_tokens']:>7} -> {b['prompt_tokens']:>7} tokens: "
                      f"{(tb - ta) / dn * 1000:>6.0f} ms per 1K added tokens", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
