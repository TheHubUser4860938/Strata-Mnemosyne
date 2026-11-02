#!/usr/bin/env python3
"""bench/p1/prefill_ab.py - one instrument, two models: how fast does the prompt get read?

WHY THIS EXISTS. On 2026-10-30 the Heretic v2 IQ4_NL boot printed prefill of roughly 1.6k tok/s against the
4,643 tok/s this box measured for huihui UD-Q4_K_XL on a 305,218-token read.  The owner's question was
"did the unlock fail on the GPU?"  That question has two answers - the card's tensor rate (tensor_rate.cu)
and what the engine actually sustains per model - and they are not the same measurement: a prompt read is
MoE-expert-bound, and the two models ship different expert quantizations (IQ4_NL vs UD-Q4_K_XL), so the
gap can be the dequant path, the expert cache, or the tensor rate.  This script prices the last-mile number
with everything else held fixed: SAME prompt text, SAME sampling, SAME max_tokens, run on whichever model
is serving 8005.  Run it once per model and compare the two lines.

Reads the engine's own usage counts (prompt_tokens), not my estimate of them, and reports the median of
`--repeats` (the owner's bench law: temp 1.0, at least three repeats, durable logs under ~/Strata-data/bench).

  .venv/bin/python bench/p1/prefill_ab.py --tokens 40000 --repeats 3 --tag heretic-iq4_nl
  .venv/bin/python bench/p1/prefill_ab.py --tokens 40000 --repeats 3 --tag huihui-ud-q4_k_xl
"""
import argparse, json, statistics, sys, time, urllib.request

BASE = "http://127.0.0.1:8005/v1"

# A fixed, English, high-entropy-per-line block; the tokenizer's rate decides the prompt size, and the same
# text on both models is what makes the two numbers comparable.  Quoted from The Federalist No. 10 (public
# domain, and this box's own founding_corpus holds it as a primary source).
TOKENS_PER_COPY = 58    # measured 2026-10-30 from the ladder slope.  CAVEAT that bit me twice: the API's
                          # prompt_tokens INCLUDES the standing prefix - the persona cartridge plus the recall
                          # block, ~11,216 tokens on this box - so every request here is ~11,216 + copies x 58.
                          # That floor sits ABOVE STRATA_PREFILL_CPU_SHARE's band (chunks < 1,024, MAX 3,072),
                          # which is why the CPU share cannot fire for our traffic.
PARA = (
    "Among the numerous advantages promised by a well constructed Union, none deserves to be more accurately "
    "developed than the utility of it in controlling the factions which arise among the modern classes of "
    "manufacturers and merchants, a species of civil society which has made a considerable figure in the "
    "polished and sophisticated nations of Europe. "
)


def ask(model_hint: str, tokens: int, repeats: int, max_tokens: int, temperature: float):
    rows = []
    for i in range(repeats):
        # The nonce goes at the FRONT, not the end: the conversation cache is keyed on the prefix, so a suffix
        # change leaves repeats 2 and 3 as cache hits - measured on 2026-10-30 as 28.27 s cold against 0.97 s
        # warm on the SAME 79,496 tokens, a 29x spread that is the cache and not the model.  A fresh head makes
        # every repeat a full read, which is the quantity the two models are compared on.
        prompt = f"[prefill_ab run {i} of {repeats}] " + PARA * max(1, int(tokens / TOKENS_PER_COPY))
        body = {"model": model_hint, "temperature": temperature, "top_p": 0.9, "max_tokens": max_tokens,
                "reasoning_effort": "none",                      # prefill is what is being timed
                "messages": [{"role": "user", "content": prompt + "\nAnswer in one short sentence."}]}
        req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                    headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=1800) as r:
            got = json.load(r)
        dt = time.perf_counter() - t0
        u = got.get("usage", {})
        pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        rows.append((pt, ct, dt))
        print(f"    repeat {i + 1}: {pt:>7,} prompt tokens, {ct:>4,} answer tokens, {dt:6.2f} s "
              f"-> {pt / dt:7.0f} tok/s in, {ct / dt:5.1f} tok/s out", flush=True)
    return rows


def ladder(model_hint: str, reps: int, temperature: float) -> list:
    """Walk the chunk sizes STRATA_PREFILL_CPU_SHARE targets: one copy is ~490 tokens, so 1..7 copies span
    490 - 3,430 - the band where the code comment prices the CPU share at -20..-35% (512 and 1,000 tokens),
    and where MAX=3072 widens the default 1,024-token cap.  Below --prefill's chunk size a prompt is ONE
    chunk, so prompt size IS chunk size here."""
    out = []
    for copies in (1, 2, 3, 4, 6, 7):   # the rungs land ~58 tokens apart ON TOP of the ~11.2k standing prefix
        rows = ask(model_hint, copies * TOKENS_PER_COPY, reps, 32, temperature)
        rates = [pt / dt for pt, ct, dt in rows if pt]
        med = statistics.median(rates)
        out.append((rows[0][0], med))
        print(f"  {rows[0][0]:>6,} tokens: median {med:7.0f} tok/s  = {1e6/med:7.1f} us/token", flush=True)
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", type=int, default=40000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=48)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--ladder", action="store_true",
                    help="walk 490-3,430-token prompts: the STRATA_PREFILL_CPU_SHARE band")
    ap.add_argument("--out", default="/home/eugene/Strata-data/bench/p1/prefill-ab.jsonl")
    a = ap.parse_args()
    health = json.load(urllib.request.urlopen(BASE.replace("/v1", "") + "/health", timeout=60))
    model = health.get("model")
    print(f"  serving: {model}   (asked as {a.tag})")
    if a.ladder:
        pts = ladder(model, a.repeats, a.temperature)
        with open(a.out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": int(time.time()), "tag": a.tag, "model": model, "ladder": pts,
                                 "temperature": a.temperature, "repeats": a.repeats}) + "\n")
        print(f"  appended ladder to {a.out}")
        return 0
    rows = ask(model, a.tokens, a.repeats, a.max_tokens, a.temperature)
    rates = [pt / dt for pt, ct, dt in rows if pt]
    med = statistics.median(rates)
    print(f"  {a.tag}: median prefill {med:,.0f} tok/s over {len(rates)} repeats at {a.temperature} C, "
          f"{rows[0][0]:,} prompt tokens")
    with open(a.out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": int(time.time()), "tag": a.tag, "model": model, "tokens": rows[0][0],
                             "repeats": len(rates), "temperature": a.temperature,
                             "median_tok_s": round(med, 1),
                             "per_repeat": [round(r, 1) for r in rates]}) + "\n")
    print(f"  appended to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
