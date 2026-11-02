#!/usr/bin/env python3
"""Is the pinned prefill host core the critical path? Sample host and GPU together.

The engine pins its host thread to one CPU during prefill (strata/platform/aux_cpus.hpp;
`--aux-cpus` moves *helpers* off that CPU, it does not spread the host thread itself).
The Ada speed-select unlock doubles fp16/bf16/tf32 tensor issue rate, which makes the
GPU side faster and therefore shifts the balance toward the host - so "would 2 or 4
cores help prefill now?" is a question about who is waiting on whom, not about how
busy each side looks on its own.

This probe answers that directly. While one fresh ~32K-token prompt prefills it samples
per-CPU jiffies from /proc/stat and the GPU's own utilization/clock from nvidia-smi at
the same rate, then reports:

  - the busiest host core: peak and mean busy over the prefill window
  - the GPU: median utilization, its 10th percentile, and the share of samples below
    90% - which is what "the GPU is starved while the host core is pegged" looks like

A GPU that stays near 100% while one core is pegged means the host core is running in
parallel, not in series, and more cores buy nothing. A GPU that dips in step with a
pegged core means the host work is on the critical path, and spreading it could pay.

Nothing is changed: one HTTP request, reads of /proc and nvidia-smi.

Usage: python3 bench/probes/2026-10-29-prefill-critical-path-probe.py [--tokens 32768]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read_cpus() -> list[tuple[int, int]]:
    out = []
    for line in Path("/proc/stat").read_text().splitlines():
        if not line.startswith("cpu"):
            break
        f = [int(x) for x in line.split()[1:]]
        idle = f[3] + (f[4] if len(f) > 4 else 0)
        out.append((sum(f) - idle, sum(f)))
    return out


def chat(base: str, text: str, max_tokens: int = 24, timeout: float = 1800) -> dict:
    body = {"model": "strata", "stream": True, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": text}]}
    req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                headers={"Content-type": "application/json"})
    first, timings, usage = None, None, None
    start = time.perf_counter()
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
    return {"first": first if first is not None else time.perf_counter() - start,
            "first_seen": first is not None, "usage": usage or {}, "timings": timings or {}}


def gpu_sample() -> tuple[float, float]:
    o = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,clocks.sm", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=10).stdout.strip()
    u, c = o.split(",")
    return float(u), float(c)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8005")
    ap.add_argument("--tokens", type=int, default=32768)
    ap.add_argument("--hz", type=float, default=4.0)
    args = ap.parse_args()

    words = [w for w in (REPO / "docs/DETAILS.md").read_text(encoding="utf-8", errors="replace").split()
             if w.isalpha() and len(w) > 2]
    rng = random.Random("critical-path")
    pool = words[:20000]
    rng.shuffle(pool)

    def build(words_n: int, tag: str) -> str:
        # draw with replacement: the pool is a fixed slice of real prose, so a long prompt
        # cycles it rather than silently capping at the pool's length
        return f"CP-PROBE {tag} || " + " ".join(rng.choice(pool) for _ in range(words_n))

    base = args.url.rstrip("/")
    n_words = int(args.tokens / 1.25)
    for attempt in range(5):
        r = chat(base, build(n_words, f"sz{attempt}"))
        got = r["usage"].get("prompt_tokens") or 0
        if got and abs(got - args.tokens) / args.tokens < 0.06:
            break
        if got:
            n_words = max(1, int(n_words * args.tokens / got))
    sized = r["usage"].get("prompt_tokens")
    print(f"sized {n_words} words -> {sized} prompt tokens", flush=True)

    period = 1.0 / args.hz
    stop = threading.Event()
    host_rows: list[list[float]] = []
    gpu_rows: list[tuple[float, float]] = []

    def sampler() -> None:
        prev = read_cpus()
        while not stop.is_set():
            t0 = time.perf_counter()
            try:
                g = gpu_sample()
            except Exception:  # noqa: BLE001 - a dropped sample must not kill the run
                g = (float("nan"), float("nan"))
            time.sleep(max(0.0, period - (time.perf_counter() - t0)))
            cur = read_cpus()
            host_rows.append([100.0 * (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0
                              for (b0, t0), (b1, t1) in zip(prev[1:], cur[1:])])
            gpu_rows.append(g)
            prev = cur

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    time.sleep(period * 2)
    res = chat(base, build(n_words, f"t{int(time.time()) % 100000}"))
    time.sleep(period * 2)
    stop.set()
    th.join(timeout=5)

    u, ti = res["usage"], res["timings"]
    pm = (ti.get("prompt_ms") or 0) / 1000.0
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    # the window: every sample from the first where GPU util rises off idle to the last busy one
    busy_idx = [i for i, (g, _) in enumerate(gpu_rows) if g and g > 30]
    lo, hi = (busy_idx[0], busy_idx[-1] + 1) if busy_idx else (0, len(gpu_rows))
    n_prompt = max(1, int(pm / period)) if pm else (hi - lo)   # the window ends with prompt_ms, not with the decode tail
    hi = min(hi, lo + n_prompt)
    win_gpu = [g for g, _ in gpu_rows[lo:hi] if g == g]
    win_clk = [c for _, c in gpu_rows[lo:hi] if c == c]
    win_host = host_rows[lo:hi]
    if not win_gpu or not win_host:
        print("no window captured - is the server up?", flush=True)
        return 1
    per_core = [[row[i] for row in win_host] for i in range(len(win_host[0]))]
    top = sorted(per_core, key=lambda c: max(c), reverse=True)[:4]
    print(f"prompt {u.get('prompt_tokens')} tokens, {cached} reused, {u.get('prompt_tokens', 0) - cached} read; "
          f"engine prompt {ti.get('prompt_ms')}ms = {ti.get('prompt_per_second')} tok/s; first token {res['first']:.2f}s{"" if res["first_seen"] else " (no delta; fell back to stream end)"}", flush=True)
    print(f"window {len(win_gpu)} samples ~{(hi-lo)*period:.1f}s (engine prompt {pm:.1f}s)", flush=True)
    print(f"GPU util: median {st.median(win_gpu):.0f}%  p10 {sorted(win_gpu)[max(0, len(win_gpu)//10)]:.0f}%  "
          f"min {min(win_gpu):.0f}%  below 90%: {sum(1 for g in win_gpu if g < 90)}/{len(win_gpu)} samples", flush=True)
    if win_clk:
        print(f"GPU SM clock: median {st.median(win_clk):.0f} MHz  min {min(win_clk):.0f}  max {max(win_clk):.0f}", flush=True)
    print("busiest host cores, per-sample max%:  " + "  ".join(f"{max(c):.0f}" for c in top), flush=True)
    print("busiest host cores, per-sample mean%: " + "  ".join(f"{st.mean(c):.0f}" for c in top), flush=True)
    pegged = sum(1 for row in win_host if max(row) > 90)
    print(f"samples with a core pegged (>90%): {pegged}/{len(win_host)};  "
          f"samples with that core pegged AND GPU under 90%: "
          f"{sum(1 for i, row in enumerate(win_host) if max(row) > 90 and win_gpu[min(i, len(win_gpu)-1)] < 90)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
