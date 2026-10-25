#!/usr/bin/env python3
"""p4_run - GEOMETRY-MATCHED cart contribution at temp 1.0 (2026-10-25, fresh boot).

P3 taught us the floor and the C-line ran different geometries (standing restore re-evals
the whole 6.9K persona as fresh text; compose restore caches it). So subtracting one from
the other was apples-vs-oranges. This run holds geometry fixed and varies only whether a
cart's ROWS EXIST under the question:

  CSTATE     full compose [c4 | mam | merge], each gold asked state-only (bodies never
             re-sent), restore per gold. G3 arm-C geometry at the new temp. n=30/gold x3.
  LOO-c4     compose [mam | merge]         - c4's golds asked; c4's rows absent.
  LOO-mam    compose [c4 | merge]          - mam's golds asked.
  LOO-merge  compose [c4 | mam]            - merge's golds asked.

NET per cart = CSTATE(cart's golds) - LOO(cart's golds): the contribution of the cart's
STATE ROWS with persona, prompt shape, index line, temp and geometry all held constant.
This is the number the state-only research line lives or dies by. G3's control (n=3,
merge only) hinted at it; this does all three carts at n=30.

temp 1.0, max_tokens 500, block off, tool off, 3 passes. Compose guard: n_saved<10K.
bench/p1/p4_<tag>/.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot, norm, IDK          # noqa: E402
from pu_run import chat_u, classify_u, STATE_LEAD, HDR   # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
CART_OF = {g: c for g, c, _, _ in GOLDS}
CARTS = ("c4-results", "mam-test745", "merge-notes")
LEAD_N = {3: "three short notes", 2: "two short notes"}


def lead_of(bodies):
    return (f"You are about to learn {LEAD_N[len(bodies)]} carried as carts. Learn them; "
            "acknowledge with OK only.\n\n"
            + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in sorted(bodies)))


def main():
    n_pass = 3
    standing = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
    assert standing, "no standing cart"
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    bodies = {n: carts[n]["sources"]["text"] for n in CARTS}
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p4_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p4_rows.jsonl")
    rows_f = open(rows_path, "w")
    print(f"P4 standing={standing} passes={n_pass} temp=1.0 geometry-matched net read", flush=True)

    files = {}
    for drop in (None,) + CARTS:
        name = "CSTATE" if drop is None else f"LOO-{drop.split('-')[0]}"
        sub = {n: b for n, b in bodies.items() if n != drop} if drop else bodies
        fname = f"P4_{name}_{tag}.bin"
        slot("restore", standing)
        ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": lead_of(sub)}])
        r = slot("save", fname)
        saved = r.get("n_saved") or 0
        print(f"  compose {name}: saved {saved} rows" + ("" if saved < 10000 else "  FLAG!"),
              flush=True)
        files[name] = fname

    def row(phase, gid, cart, p, ans, pt, ca, dt, fr):
        rows_f.write(json.dumps({"tag": tag, "phase": phase, "gold": gid, "cart": cart,
                                 "pass": p, "cls": classify_u(ans, gid, NOVEL_VS),
                                 "ans": ans[:160], "ptok": pt, "eval": pt - ca,
                                 "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    def ask(phase, fname, golds, p):
        for gid, cart, q, _ in golds:
            slot("restore", fname)
            ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
            row(phase, gid, cart, p, ans, pt, ca, dt, fr)

    for p in range(1, n_pass + 1):
        ask("CSTATE", files["CSTATE"], GOLDS, p)
        for c in CARTS:
            ask(f"LOO-{c.split('-')[0]}", files[f"LOO-{c.split('-')[0]}"],
                [g for g in GOLDS if CART_OF[g[0]] == c], p)
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(phase):
        sel = [r for r in rows if r["phase"] == phase]
        return sum(1 for r in sel if r["cls"] == "gold") / len(sel) if sel else 0.0

    def medev(phase):
        ev = sorted(r["eval"] for r in rows if r["phase"] == phase)
        return ev[len(ev) // 2] if ev else 0

    lines = [f"P4 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"temp=1.0 maxtok=500 standing={standing} geometry-matched (restore compose per ask)"]
    cs = rate("CSTATE")
    lines.append(f"  CSTATE all-golds {cs:.3f} (n=90) | med eval {medev('CSTATE')} tok "
                 f"(G3 arm C was 0.256 raw at 0.8)")
    for c in CARTS:
        k = c.split("-")[0]
        sel = [r for r in rows if r["phase"] == "CSTATE" and r["cart"] == c]
        cs_c = sum(1 for r in sel if r["cls"] == "gold") / len(sel)
        loo = rate(f"LOO-{k}")
        lines.append(f"  cart {c:12s}: in-compose {cs_c:.3f} | without-its-rows (LOO) {loo:.3f} "
                     f"| NET {cs_c - loo:+.3f}")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p4_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
