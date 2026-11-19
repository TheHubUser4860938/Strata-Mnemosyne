#!/usr/bin/env python3
"""p11_run - the cache-geometry mechanism probe (2026-10-26, after grad2): WHY does
prefix mode's parked conversation stop reusing at long-answer depth (deep-bucket med
11,400 ~ a full-history re-read) while anchor mode keeps reusing (4,403)? grad2 shipped
the anchor on the owner's ratification; this probe is for the record, not for the ship.

Five arms, one 25-turn window each (GOLDS[:25], real generated answers, temp default,
max_tokens 500, scorer for the sanity column only - the PRIMARY output is the eval curve
per arm, medians of pos 1-8 / 9-16 / 17-25). One boot; block default = tail (the box
config); the carts are the same three fresh rows grad2 measured.

  P1 REPRO  prefix carts, tail block           - reproduce grad2-P's growth
  P2 NOBLK  prefix carts, block OFF            - isolate the volatile tail block
  P3 ANCHOR anchor carts, tail block           - the shipped arm, the flat control
  P4 BLKON  no carts, tail block               - isolate the block alone
  P5 PASTE  prefix carts, block OFF, a static ~300-tok FILLER pasted into every user
            message CLIENT-SIDE (P10's geometry: the bytes enter the client's history
            and go stable) - the geometry control

PREDICTIONS, FROZEN BEFORE THE RUN:
  P1 grows to a deep-bucket median >= 4,000 tok (if it does not, the grad2 finding is
     boot/traffic-dependent and that is the headline - say so).
  P2 flat (deep median <= 1,500) => the volatile TAIL BLOCK is what breaks prefix's
     history reuse; still growing => the head carts interact with something else.
  P3 mild slope like grad2-N (~2,500-4,500) - the shipped shape.
  P4 flat <= 800 - the block alone is cheap at the tail.
  P5 flat <= 700 - bytes that persist in the client's history cache fully, which is
     the geometry difference P10's flat 350 could not see (it pasted; the server injects).
Read: P2 flat + P4 flat + P1 growing = volatile-tail-block x head-carts is the poison
pair; P5 flat alongside P1 growing confirms it is cache GEOMETRY, not token count.
bench/p1/p11_<tag>/.
"""
import datetime
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS                                # noqa: E402
from pu_run import classify_u                           # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
BASE = "http://127.0.0.1:8005"
CARTS = "c4-results,mam-test745,merge-notes"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
FILLER = ("Cache-geometry probe filler, stable bytes riding inside the client's "
          "history every turn. " * 30)
N_TURN = 25


def chat(msgs, hdrs=None):
    body = {"model": "m", "max_tokens": 500, "reasoning_effort": "off", "messages": msgs}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(hdrs or {})})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=600))
    u = d.get("usage", {})
    return (d["choices"][0]["message"]["content"] or "",
            int(u.get("prompt_tokens") or 0),
            int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            round(time.time() - t0, 2))


def main():
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p11_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_f = open(os.path.join(out_dir, "p11_rows.jsonl"), "w")
    print(f"P11 filler={len(FILLER):,} chars, {N_TURN}-turn windows, tag={tag}", flush=True)

    for arm, hdr in (("P1", {"X-Strata-Carts": CARTS, "X-Strata-Carts-Mode": "prefix"}),
                     ("P2", {"X-Strata-Carts": CARTS, "X-Strata-Carts-Mode": "prefix",
                             "X-Strata-Memory-Block": "off"}),
                     ("P3", {"X-Strata-Carts": CARTS, "X-Strata-Carts-Mode": "anchor"}),
                     ("P4", {"X-Strata-Memory-Block": "tail"}),
                     ("P5", {"X-Strata-Carts": CARTS, "X-Strata-Carts-Mode": "prefix",
                             "X-Strata-Memory-Block": "off"})):
        conv = []
        for pos, (gid, cart, q, _) in enumerate(GOLDS[:N_TURN]):
            msg = q + "\n\n" + FILLER if arm == "P5" else q
            ans, pt, ca, dt = chat(conv + [{"role": "user", "content": msg}], dict(hdr))
            rows_f.write(json.dumps({"tag": tag, "arm": arm, "pos": pos, "gold": gid,
                                     "cart": cart, "cls": classify_u(ans, gid, NOVEL_VS),
                                     "eval": pt - ca, "alen": len(ans.split()),
                                     "s": dt}) + "\n")
            rows_f.flush()
            conv += [{"role": "user", "content": msg}, {"role": "assistant", "content": ans}]
        print(f"  arm {arm} done", flush=True)
    rows_f.close()

    rows = [json.loads(l) for l in open(os.path.join(out_dir, "p11_rows.jsonl"))]

    def bucket(arm, lo, hi):
        ev = sorted(r["eval"] for r in rows if r["arm"] == arm and lo <= r["pos"] < hi)
        return ev[len(ev) // 2] if ev else 0

    lines = [f"p11 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag}"
             " (predictions frozen in the runner docstring before the run)"]
    for arm, name in (("P1", "REPRO "), ("P2", "NOBLK "), ("P3", "ANCHOR"),
                      ("P4", "BLKON "), ("P5", "PASTE ")):
        b = [bucket(arm, 0, 8), bucket(arm, 8, 16), bucket(arm, 16, 25)]
        rec = sum(1 for r in rows if r["arm"] == arm and r["cls"] == "gold")
        lines.append(f"  {arm} {name}: buckets {b[0]:6d} {b[1]:6d} {b[2]:6d} "
                     f"(pred growth {'>' if arm in ('P1',) else '<='} "
                     f"{'4,000' if arm == 'P1' else '1,500' if arm == 'P2' else '4,500' if arm == 'P3' else '800' if arm == 'P4' else '700'}"
                     f" tok) | recall sanity {rec}/{N_TURN}")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p11_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
