#!/usr/bin/env python3
"""p10_run - the recall-block POSITION probe (2026-10-26): graduation showed the A-arm's
eval/ask GROWS with conversation depth (1,076 -> 2,350 -> 3,608 tok) while the B-arm sits
FLAT - fingerprint of the volatile tier-3 block riding BETWEEN the standing/carts prefix and
the conversation: every turn's block bytes differ, so everything behind them re-evaluates.
If the block rode at the TAIL (after history, as part of the newest user turn), history
should cache again and cost go flat. This probe measures the mechanism from the client side,
no server change:

  H (HEAD, today)    block ON (server injects it at the head), bare gold questions.
  T (TAIL, simulated) block OFF per request (X-Strata-Memory-Block: off) + the client pages
                      its own recall rows (POST /memory op=search for that turn's question)
                      and appends them to its own user message - volatile bytes again, but in
                      the newest turn only, where the cache treats them as an append.

24-turn windows x 2 passes per arm (growth is a within-window slope; passes gauge noise).
The questions are the same golds as A6/grad (short - the regime where H grew). Prediction
from the cache semantics: H grows like grad's A; T sits flat near (question + block). If T
confirms, moving the block server-side is a one-function change and graduation's "attach
costs ~2K/ask" headline shrinks to the block's own paging cost - which attach never caused.
bench/p1/p10_<tag>/.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS                                  # noqa: E402
from grad_run import chat, post                           # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
CARTS = "c4-results,mam-test745,merge-notes"
N_TURN, N_PASS = 24, 2


def main():
    standing = post("/memory?limit=1", None)["stats"]["cartridges"]["file"]
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p10_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_f = open(os.path.join(out_dir, "p10_rows.jsonl"), "w")
    print(f"P10 standing={standing} block-position probe: H head vs T tail, "
          f"{N_TURN}-turn windows x {N_PASS}", flush=True)

    for arm in ("H", "T"):
        for p in range(1, N_PASS + 1):
            conv = []
            for i, (gid, cart, q, _) in enumerate(GOLDS[:N_TURN]):
                hdrs = {"X-Strata-Carts": CARTS}
                msg = q
                if arm == "T":
                    hdrs["X-Strata-Memory-Block"] = "off"
                    hits = post("/memory", {"op": "search", "q": q, "limit": 8}).get("hits", [])
                    blk = "RECALL - paged fresh for this turn, may be stale:\n" + "\n".join(
                        f"{n}. [{h.get('class', '?')}] {h.get('text', '')}"
                        for n, h in enumerate(hits, 1))
                    msg = q + "\n\n" + blk
                ans, pt, ca, dt = chat(conv + [{"role": "user", "content": msg}], hdrs)
                rows_f.write(json.dumps({"tag": tag, "arm": arm, "pass": p, "pos": i,
                                         "gold": gid, "ans": ans[:80], "ptok": pt,
                                         "eval": pt - ca, "s": dt}) + "\n")
                rows_f.flush()
                conv += [{"role": "user", "content": msg},
                         {"role": "assistant", "content": ans}]
            print(f"  arm {arm} pass {p}/{N_PASS} done", flush=True)
    rows_f.close()

    rows = [json.loads(l) for l in open(os.path.join(out_dir, "p10_rows.jsonl"))]

    def medev(arm, lo, hi):
        sel = sorted(r["eval"] for r in rows if r["arm"] == arm and lo <= r["pos"] < hi)
        return sel[len(sel) // 2] if sel else 0

    lines = [f"P10 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"(grad A growth baseline: 1,076 -> 2,350 -> 3,608 tok by bucket, 30-turn windows)",
             f"  H head : buckets 1-8 {medev('H', 0, 8)} | 9-16 {medev('H', 8, 16)} | "
             f"17-24 {medev('H', 16, 24)} tok",
             f"  T tail : buckets 1-8 {medev('T', 0, 8)} | 9-16 {medev('T', 8, 16)} | "
             f"17-24 {medev('T', 16, 24)} tok",
             "  reading: FLAT T + growing H confirms the head block as the history-cache "
             "breaker; the server-side move is then a one-function change to try for real."]
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p10_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
