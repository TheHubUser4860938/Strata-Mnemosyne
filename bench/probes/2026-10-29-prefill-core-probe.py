#!/usr/bin/env python3
"""How many host cores actually work during a prefill?

The question this answers: now that the Ada speed-select unlock has doubled the
fp16/bf16/tf32 tensor issue rate, is the CPU side (the decode pool, --pool-workers)
close enough to the limit that shrinking or growing it would move prompt speed?

Method: sample /proc/stat per CPU every 0.4 s while one fresh ~32K-token prompt is
prefilled, then report, over the busy window only, how many host cores exceeded 50%
and what the busiest cores were doing. The engine's own prompt_ms and
prompt_per_second come from the answer's timings, so the window is real work, not
idle inference. Nothing here changes state: one HTTP request and reads of /proc.

Usage: python3 bench/probes/2026-10-29-prefill-core-probe.py [--tokens 32768]
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORDS = (Path(__file__).resolve().parent / "corpus.txt")


def read_cpus() -> list[tuple[int, int]]:
    """-> [(busy_jiffies, total_jiffies)] per CPU, index 0 is the aggregate line."""
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
    return {"first": first, "usage": usage or {}, "timings": timings or {}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8005")
    ap.add_argument("--tokens", type=int, default=32768)
    ap.add_argument("--warm-tokens", type=int, default=2048)
    args = ap.parse_args()

    words = [w for w in (REPO / "docs/DETAILS.md").read_text(encoding="utf-8", errors="replace").split()
             if w.isalpha() and len(w) > 2]
    rng = random.Random("core-probe")
    pool = words[:20000]
    rng.shuffle(pool)

    def build(target: int, tag: str) -> str:
        w = max(1, int(target / 1.25))
        return f"CORE-PROBE {tag} || " + " ".join(rng.sample(pool, min(w, len(pool))) if w <= len(pool)
                                                  else pool[:w % len(pool)] + pool)

    # Size the prompt on the engine's own count, then take the timed shot.
    base = args.url.rstrip("/")
    probe_words = int(args.tokens / 1.25)
    for attempt in range(3):
        r = chat(base, build(probe_words, f"sz{attempt}"))
        got = r["usage"].get("prompt_tokens") or 0
        if got and abs(got - args.tokens) / args.tokens < 0.06:
            break
        if got:
            probe_words = max(1, int(probe_words * args.tokens / got))
    print(f"sizing: {probe_words} words -> {r['usage'].get('prompt_tokens')} prompt tokens", flush=True)

    stop = threading.Event()
    samples: list[list[float]] = []

    def sampler() -> None:
        prev = read_cpus()
        while not stop.is_set():
            time.sleep(0.4)
            cur = read_cpus()
            row = []
            for (b0, t0), (b1, t1) in zip(prev, cur):
                row.append(100.0 * (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0)
            samples.append(row)
            prev = cur

    t = threading.Thread(target=sampler, daemon=True)
    t.start()
    time.sleep(0.5)
    res = chat(base, build(probe_words, f"timed{int(time.time()) % 10000}"))
    time.sleep(0.5)
    stop.set()
    t.join(timeout=3)

    u, ti = res["usage"], res["timings"]
    ncpu = len(samples[0]) - 1 if samples else 0
    window = [s for s in samples if s[0] > 15.0]          # aggregate busy: the prefill itself
    if not window:
        print("no busy window captured - is the server up?", flush=True)
        return 1
    per_core = [[s[i] for s in window] for i in range(1, ncpu + 1)]
    peak = sorted((max(c) for c in per_core), reverse=True)
    mean = sorted((sum(c) / len(c) for c in per_core), reverse=True)
    over50 = sum(1 for c in per_core if max(c) > 50)
    over20 = sum(1 for c in per_core if max(c) > 20)
    print(f"prompt {u.get('prompt_tokens')} tokens ({u.get('prompt_tokens_details', {}).get('cached_tokens', 0)} reused), "
          f"engine prompt {ti.get('prompt_ms')}ms = {ti.get('prompt_per_second')} tok/s, "
          f"first token {res['first']:.2f}s", flush=True)
    print(f"busy window {len(window)} samples ({len(window)*0.4:.1f}s) of {ncpu} logical CPUs", flush=True)
    print(f"cores over 50% busy: {over50}   over 20%: {over20}", flush=True)
    print("busiest cores, peak%:  " + " ".join(f"{v:.0f}" for v in peak[:8]), flush=True)
    print("busiest cores, mean%:  " + " ".join(f"{v:.0f}" for v in mean[:8]), flush=True)
    print(f"aggregate busy mean {sum(s[0] for s in window)/len(window):.0f}% "
          f"max {max(s[0] for s in window):.0f}%", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
