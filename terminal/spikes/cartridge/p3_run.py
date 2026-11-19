#!/usr/bin/env python3
"""p3_run - the post-reboot retest (2026-10-25, owner rebooted 14:5x; boot carries
STRATA_KV_ROT=OFF - verified from /proc/<engine>/environ, so this run is a TEST-RETEST
of the corrected C-line on a byte-identical config, fresh slot, and it pre-registers
the KV_ROT pair against itself. bench/p1/p3_<tag>/.

Phases (temp 1.0, max_tokens 500, block off, tool off, 3 passes per the owner's rule):
  C30    all 30 novel golds with the three carts COMPOSED (G3 geometry) - retest of the
         C-line raw band on the fresh boot.
  GUESS  the same 30 golds with NO cart (persona floor) - retest of the floor the public
         correction stands on (was 0.200 overall; merge 0.333, c4 0.233, mam 0.033).
  WORLD  capitals: cart-mounted vs bare (was 0.433 vs 0.367, delta +0.067 noise).
Net read = C30 minus GUESS, per cart - the corrected phenomenon, reproduced or not.
Compose guard (new law after the 205K-row race): n_saved must be < 10,000 rows or FLAG.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot, norm, IDK          # noqa: E402
from pu_run import chat_u, classify_u, STATE_LEAD, HDR   # noqa: E402
from p2_run import WORLD, WORLD_VS, GEO_LEAD             # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
CART_OF = {g: c for g, c, _, _ in GOLDS}
LEAD = ("You are about to learn three short notes carried as carts. Learn them; "
        "acknowledge with OK only.\n\n")


def main():
    n_pass = 3
    st = post("/memory?limit=1", None, [])["stats"]
    standing = (st.get("cartridges") or {}).get("file")
    assert standing, "no standing cart"
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    bodies = {n: carts[n]["sources"]["text"] for n in sorted(carts)}
    lead3 = LEAD + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in sorted(carts))

    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p3_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p3_rows.jsonl")
    rows_f = open(rows_path, "w")
    f3, fg = f"P3_COMPOSE_{tag}.bin", f"P3_GEO_{tag}.bin"
    print(f"P3 standing={standing} carts={sorted(carts)} passes={n_pass} temp=1.0 "
          f"(boot: KV_ROT verified OFF - retest mode)", flush=True)

    def build(fname, lead, ack_holder):
        slot("restore", standing)
        ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": lead}])
        r = slot("save", fname)
        saved = r.get("n_saved") or 0
        flag = "" if saved < 10000 else "  FLAG: slot bloat, geometry suspect!"
        print(f"  compose {fname}: lead eval {pt - ca} tok, saved {saved} rows{flag}", flush=True)
        ack_holder[0] = ack

    a3, ag = [None], [None]
    build(f3, lead3, a3)
    build(fg, GEO_LEAD, ag)

    def row(phase, gid, cart, p, ans, pt, ca, dt, fr, vs):
        rows_f.write(json.dumps({"tag": tag, "phase": phase, "gold": gid, "cart": cart,
                                 "pass": p, "cls": classify_u(ans, gid, vs), "ans": ans[:160],
                                 "ptok": pt, "eval": pt - ca, "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    for p in range(1, n_pass + 1):
        # C30: composed, 3 conversations of 10 (restore once per conversation, turns pile up)
        slot("restore", f3)
        conv = [{"role": "user", "content": lead3}, {"role": "assistant", "content": a3[0]}]
        for gid, cart, q, _ in GOLDS:
            ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": q}])
            row("C30", gid, cart, p, ans, pt, ca, dt, fr, NOVEL_VS)
            conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        # GUESS: floor, restore standing per gold
        for gid, cart, q, _ in GOLDS:
            slot("restore", standing)
            ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
            row("GUESS", gid, cart, p, ans, pt, ca, dt, fr, NOVEL_VS)
        # WORLD: cart vs bare
        for gid, q, _ in WORLD:
            slot("restore", fg)
            ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
            row("WORLD-CART", gid, "world", p, ans, pt, ca, dt, fr, WORLD_VS)
        for gid, q, _ in WORLD:
            slot("restore", standing)
            ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
            row("WORLD-BARE", gid, "world", p, ans, pt, ca, dt, fr, WORLD_VS)
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(phase, cart=None):
        sel = [r for r in rows if r["phase"] == phase and (cart is None or r["cart"] == cart)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    def medev(phase):
        ev = sorted(r["eval"] for r in rows if r["phase"] == phase)
        return ev[len(ev) // 2] if ev else 0

    lines = [f"P3 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"passes={n_pass} temp=1.0 maxtok=500 standing={standing} KV_ROT=off (retest)"]
    for ph in ("C30", "GUESS"):
        r_all, n = rate(ph)
        per = {c: rate(ph, c)[0] for c in sorted(carts)}
        lines.append(f"  {ph:6s} {r_all:.3f} (n={n}) | " + " ".join(
            f"{c.split('-')[0]}={per[c]:.3f}" for c in per) + f" | med eval {medev(ph)} tok")
    net = {c: rate("C30", c)[0] - rate("GUESS", c)[0] for c in sorted(carts)}
    lines.append("  NET (C30 - GUESS): " + " ".join(f"{c.split('-')[0]}={net[c]:+.3f}" for c in net)
                 + "   (last boot was ~+0.07..+0.17; P2 floors were merge .333 c4 .233 mam .033)")
    wc, _ = rate("WORLD-CART"); wb, _ = rate("WORLD-BARE")
    lines.append(f"  WORLD-CART {wc:.3f} | WORLD-BARE {wb:.3f} | delta {wc - wb:+.3f} "
                 f"(was +0.067 noise)")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p3_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
