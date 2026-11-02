#!/usr/bin/env python3
"""Prefill length sweep - is prompt attention a big enough slice to be worth an
fp16/bf16 tensor-core unlock?

The gpu-unlock module (github.com/elias-gaeros/gpu-unlock, branch rtx4090) doubles
the issue rate of tensor-core mma with fp16/bf16 inputs and fp32 accumulate. In this
engine that instruction appears in src/kernels/cuda/qsa_prompt_attn.cu only; the
expert and dense matmuls dequant to fp32 on CUDA cores, and the int8 KV and decode
attention paths use the s8/s8 mma, which the author measured as unchanged.

So the unlock can only speed the attention part of prefill, and how much depends on
what share of prefill attention takes at the prompt lengths actually served. This
probe measures that share by its shape: it sends fresh prompts (unique tag, so the
conversation cache cannot help) at growing token counts and reports prompt tok/s and
the seconds per 1K prompt tokens. Flat marginal cost means the prefill is linear work
(weights, staging) and attention is a thin slice, so a 2x attention gain buys little.
A rising marginal cost means attention is real work in the number, and the unlock has
somewhere to bite.

Against the server already running (default http://127.0.0.1:8005). Speed only; no
correctness check. Temperatures: the suite uses temperature 0 for prompt throughput,
which is deterministic and is how the community report in bench/results/ was taken.

Usage:  python3 bench/probes/2026-10-23-prefill-length-sweep.py [--url URL]
            [--api-key KEY] [--sizes 8192,16384,...] [--runs 2] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
import urllib.request
from datetime import date
from pathlib import Path

WORDS = (
    "harbour ledger granary compass anvil orchard warrant customs timber meadow "
    "quarry tollhouse muster parchment sextant pasture customs millwright warrant "
    "farrier orchard strata memory ledger note shelf cartridge muster parchment "
    "harbour timber anvil meadow quarry tollhouse compass pasture millwright farrier"
).split()


def chat(base: str, key: str, messages: list, max_tokens: int, timeout: float) -> dict:
    """One streamed chat request -> {first, total, usage, timings, err}."""
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
        headers={"Content-type": "application/json"}
        | ({"Authorization": "Bearer " + key} if key else {}),
    )
    first, total, usage, timings, err, pieces = None, 0.0, None, None, None, 0
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
                pieces += 1
                delta = "".join(
                    c.get("delta", {}).get("content") or ""
                    for c in (j.get("choices") or [])
                ) or (j.get("text") or "")
                if first is None and delta:
                    first = time.perf_counter() - start
                if j.get("usage"):
                    usage = j["usage"]
                if j.get("timings"):
                    timings = j["timings"]
    except Exception as exc:  # noqa: BLE001 - report, do not retry blind
        err = f"{type(exc).__name__}: {exc}"
    total = time.perf_counter() - start
    return {"first": first, "total": total, "usage": usage, "timings": timings, "err": err}


def prompt_text(target_tokens: int, tag: str, tokens_per_word: float = 1.0) -> str:
    """About `target_tokens` worth of random words, tagged so no cache can help."""
    rng = random.Random(tag)
    words = max(1, int(target_tokens / tokens_per_word))
    return f"UNLOCK-SWEEP {tag} || " + " ".join(rng.choice(WORDS) for _ in range(words))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8005")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--sizes", default="8192,16384,32768,65536,131072,196608")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--max-new", type=int, default=24)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    key = args.api_key

    rows: list[dict] = []
    print(f"# prefill length sweep against {base}  {date.today().isoformat()}", flush=True)
    cal = chat(base, key, [{"role": "user", "content": prompt_text(1000, "CAL-0")}], args.max_new, args.timeout)
    cal_tokens = ((cal.get("usage") or {}).get("prompt_tokens")) or 0
    tpw = cal_tokens / 1000.0 if cal_tokens else 0.0  # tokens per word, measured on this server
    print(f"calibration: 1000 words measured {cal_tokens} prompt tokens "
          f"({tpw:.3f} tokens/word) err={cal['err']}", flush=True)
    if not cal_tokens:
        print("calibration failed, is the server up and the port right?", flush=True)
        return 1

    for tokens in sizes:
        per_run = []
        for run in range(args.runs):
            tag = f"SW{tokens}-{run}-{int(time.time()) % 100000}"
            r = chat(base, key, [{"role": "user", "content": prompt_text(tokens, tag, tpw)}],
                     args.max_new, args.timeout)
            u, t = r.get("usage") or {}, r.get("timings") or {}
            row = {
                "asked_tokens": tokens,
                "run": run,
                "prompt_tokens": u.get("prompt_tokens"),
                "cached_tokens": u.get("cached_tokens"),
                "prompt_ms": t.get("prompt_ms"),
                "prompt_tps": t.get("prompt_per_second"),
                "ttft_s": round(r["first"], 3) if r["first"] else None,
                "err": r["err"],
            }
            per_run.append(row)
            rows.append(row)
            print(f"  {tokens:>7} -> prompt_n={row['prompt_tokens']} reused={row['cached_tokens']} "
                  f"prompt={row['prompt_ms']}ms {row['prompt_tps']} tok/s ttft={row['ttft_s']}s "
                  f"{'ERR ' + str(row['err']) if row['err'] else ''}", flush=True)
            if row["err"]:
                break
        good = [r for r in per_run if r["prompt_tps"] and r["prompt_tokens"]]
        if len(good) == args.runs and args.runs > 1:
            med = sorted(good, key=lambda r: r["prompt_tps"])[len(good) // 2]
            mspt = 1000.0 / med["prompt_tps"]  # seconds per 1K prompt tokens
            print(f"  ==> {tokens:>7} tokens: median {med['prompt_tps']:.1f} tok/s, "
                  f"{mspt:.3f} s per 1K tokens", flush=True)

    out = args.out or f"bench/probes/{date.today().isoformat()}-prefill-length-sweep.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"base": base, "date": date.today().isoformat(),
                                     "tokens_per_word": tpw, "rows": rows}, indent=2))
    print(f"wrote {out}", flush=True)

    good = [r for r in rows if r["prompt_tps"] and r["prompt_tokens"]]
    if len(good) >= 2:
        good.sort(key=lambda r: r["prompt_tokens"])
        print("\n# marginal cost per 1K tokens between the sizes (attention shows up here):", flush=True)
        for a, b in zip(good, good[1:]):
            dt = (1000 * b["prompt_tokens"] / b["prompt_tps"] - 1000 * a["prompt_tokens"] / a["prompt_tps"]) / 1000
            dn = (b["prompt_tokens"] - a["prompt_tokens"]) / 1000
            if dn > 0:
                print(f"  {a['prompt_tokens']:>7} -> {b['prompt_tokens']:>7}: "
                      f"{dt / dn * 1000:.0f} ms per 1K added tokens", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
