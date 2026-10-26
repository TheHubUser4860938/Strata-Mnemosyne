#!/usr/bin/env python3
"""a6_run - the rut-rate follow-up (2026-10-26): graduation's A arm was TWO perfect windows
(1.000/1.000 re-scored) and ONE collapsed tail (0.633, ten misses all in the deep end, four of
them a self-reinforcing cross-cart confusion loop: three consecutive merge-notes golds answered
"According to the MAM reference note..."). Is that collapse the depth curve biting (P8's regime:
0.5 by turn 30) or one unlucky temp-1.0 trajectory? Six more A-arm passes, same geometry as
grad's A (header X-Strata-Carts on all three carts, golds-as-turns, block ON - production
bytes), n=6 windows: each window scoring < 27/30 counts as a RUT, and the tail bucket
(positions 21-30) is reported per window. Verdict feeds S4b directly: rut rate near zero means
the 0.633 was trajectory luck and shallow windows can ship; a rut rate near 1/3 or worse means
depth is the default enemy and attach should not ship without its countermeasure.
The instrument is the graduation runner minus arms B/C; NUMTOK now carries the period fix
(g3_run, 2026-10-26) so answers quoted with their sentence period score honestly.
bench/p1/a6_<tag>/.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS                                  # noqa: E402
from pu_run import classify_u                             # noqa: E402
from grad_run import chat, post                           # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
CARTS = "c4-results,mam-test745,merge-notes"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
N_PASS = 6


def main():
    standing = post("/memory?limit=1", None)["stats"]["cartridges"]["file"]
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"a6_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_f = open(os.path.join(out_dir, "a6_rows.jsonl"), "w")
    print(f"A6 standing={standing} passes={N_PASS} rut-rate probe", flush=True)
    for p in range(1, N_PASS + 1):
        conv = []
        for i, (gid, cart, q, _) in enumerate(GOLDS):
            ans, pt, ca, dt = chat(conv + [{"role": "user", "content": q}],
                                   {"X-Strata-Carts": CARTS})
            rows_f.write(json.dumps({"tag": tag, "pass": p, "gold": gid, "cart": cart,
                                     "pos": i, "cls": classify_u(ans, gid, NOVEL_VS),
                                     "ans": ans[:140], "ptok": pt, "eval": pt - ca,
                                     "s": dt}) + "\n")
            rows_f.flush()
            conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        print(f"  pass {p}/{N_PASS} done", flush=True)
    rows_f.close()

    rows = [json.loads(l) for l in open(os.path.join(out_dir, "a6_rows.jsonl"))]

    def rate(lo=None, hi=None, passn=None):
        sel = [r for r in rows if (passn is None or r["pass"] == passn)
               and (lo is None or lo <= r["pos"] < hi)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    ev = sorted(r["eval"] for r in rows)
    per = [rate(passn=p)[0] for p in range(1, N_PASS + 1)]
    ruts = sum(1 for s in per if s < 0.90)
    a, n = rate()
    lines = [f"A6 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"rut-rate (A-arm only, block ON, 6 windows x 30 golds; grad re-scored shape was "
             f"1.000/1.000/0.633)",
             f"  overall {a:.3f} (n={n}) | per-window " + " ".join(f"{s:.3f}" for s in per)
             + f" | RUTS {ruts}/6 | tail bucket (pos 21-30) {rate(20, 30)[0]:.3f} vs shallow "
             f"{rate(0, 20)[0]:.3f} | med eval {ev[len(ev) // 2]} tok"]
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"a6_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
