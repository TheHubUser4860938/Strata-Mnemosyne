#!/usr/bin/env python3
"""p7_run - cart-count dilution (2026-10-25): C30 measured the 3-cart decay curve
(0.800/0.700/0.500 by position bucket, no suffix, temp 1.0, overall 0.667). The owner's
attach policy - "hand-picked few, never 10-deep" - needs the marginal price: with SIX
carts riding (the three real ones plus three reference carts just minted from today's
mex/virtual-context/DETAILS fetches, riding unqueried), how much faster do the same 30
golds decay? Same geometry as C30: one conversation of 30 golds on the compose, bodies
re-sent and cache-absorbed, no suffix, 3 passes, temp 1.0.
Reading: if the buckets barely move, extra riders are nearly free and "few carts" is a
tidiness rule; if the curve shifts a bucket earlier, every extra cart is taxed in turns
of recall and the attach rule must COUNT riders, not just weigh them.
bench/p1/p7_<tag>/.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot                       # noqa: E402
from pu_run import chat_u, classify_u, HDR                 # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
EXTRA = [("mex-curation", "mex_ref.txt"), ("virtual-context", "vc_ref.txt"),
         ("kv-streaming", "kv_ref.txt")]


def main():
    n_pass = 3
    standing = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    bodies = {n: carts[n]["sources"]["text"] for n in ("c4-results", "mam-test745", "merge-notes")}
    for name, fname in EXTRA:
        bodies[name] = open(os.path.join(HERE, fname)).read().strip()
    order = sorted(bodies)
    lead = ("You are about to learn six short notes carried as carts. Learn them; "
            "acknowledge with OK only.\n\n" + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in order))
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p7_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p7_rows.jsonl")
    rows_f = open(rows_path, "w")
    fname = f"P7_COMPOSE_{tag}.bin"
    slot("restore", standing)
    ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": lead}])
    r = slot("save", fname)
    saved = r.get("n_saved") or 0
    print(f"P7 standing={standing} riders={order} compose saved {saved} rows"
          + ("" if 8000 < saved < 18000 else "  FLAG: base suspect"), flush=True)

    for p in range(1, n_pass + 1):
        slot("restore", fname)
        conv = [{"role": "user", "content": lead}, {"role": "assistant", "content": ack}]
        for i, (gid, cart, q, _) in enumerate(GOLDS):
            ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": q}])
            rows_f.write(json.dumps({"tag": tag, "phase": "test", "gold": gid, "cart": cart,
                                     "pass": p, "pos": i, "cls": classify_u(ans, gid, NOVEL_VS),
                                     "ans": ans[:140], "ptok": pt, "eval": pt - ca,
                                     "s": round(dt, 2), "fr": fr}) + "\n")
            rows_f.flush()
            conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(lo=None, hi=None):
        sel = [r for r in rows if lo is None or lo <= r["pos"] < hi]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    ev = sorted(r["eval"] for r in rows)
    a, n = rate()
    lines = [f"P7 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"temp=1.0 SIX-cart compose, 30 golds, no suffix (pairs with C30)",
             f"  overall {a:.3f} (n={n}) | med eval {ev[len(ev)//2]} tok "
             f"(C30 three-cart: 0.667, buckets 0.800/0.700/0.500)",
             f"  buckets: pos 1-10 {rate(0,10)[0]:.3f} | 11-20 {rate(10,20)[0]:.3f} "
             f"| 21-30 {rate(20,30)[0]:.3f}"]
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p7_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
