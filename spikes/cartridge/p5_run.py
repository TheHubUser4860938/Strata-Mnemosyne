#!/usr/bin/env python3
"""p5_run - decomposing the long-conversation decay (2026-10-25, same boot as P3/P4):
is composed recall at turn 30 down because history is LONG (dilution / lost-in-middle)
or because the history is full of EARLIER CART ANSWERS (distractors)?

Both arms: restore the 3-cart compose once per pass, hold 26 preamble turns, then test
all 30 golds at IDENTICAL positions. They differ only in preamble content:
  D (distractor)  preamble = the first 26 golds asked and answered (cart Q&A in history)
  N (neutral)     preamble = 26 non-cart chit-chat Q&As (colors, weather, animals)
Every ask (gold and filler) carries the same suffix, "Answer in two or three full
sentences.", so history SIZE is comparable and paired against the banked C30 (0.667,
no suffix, golds at turns 3-32).

Reading the verdict:
  N >> D          -> distractors: prior cart answers poison later ones -> re-anchor/refresh
  N ~ D ~ 0.7     -> dilution: mere length hurts -> compaction or periodic re-send
  both ~ 0.9      -> neither at these depths -> C30's drop was ordering/interleaving
temp 1.0, max_tokens 500, block off, tool off, 3 passes. bench/p1/p5_<tag>/.
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
SUFFIX = " Answer in two or three full sentences."
FILLERS = [
    "What color is the sky?", "What color is the sea?", "What color is grass?",
    "Is fire hot?", "Is ice cold?", "Is the sun bright?", "What do dogs do for a sound?",
    "What do cats make for a sound?", "Do fish swim?", "Do birds fly?",
    "Are trees tall?", "Is a desert dry?", "Is the ocean vast?", "Is a mountain high?",
    "Does a river flow?", "Is rain wet?", "Does wind blow?", "Is bread baked?",
    "Is milk white?", "Is night dark?", "Are roses red?", "Is honey sweet?",
    "Is a stone heavy?", "Does snow fall cold?", "Is the moon bright at night?",
    "Are mountains made of rock?",
]


def main():
    n_pass = 3
    standing = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    bodies = {n: carts[n]["sources"]["text"] for n in sorted(carts)}
    lead = ("You are about to learn three short notes carried as carts. Learn them; "
            "acknowledge with OK only.\n\n"
            + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in sorted(carts)))
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p5_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p5_rows.jsonl")
    rows_f = open(rows_path, "w")
    fname = f"P5_COMPOSE_{tag}.bin"
    slot("restore", standing)
    ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": lead}])
    r = slot("save", fname)
    saved = r.get("n_saved") or 0
    print(f"P5 standing={standing} compose saved {saved} rows"
          + ("" if saved < 10000 else "  FLAG!"), flush=True)

    def row(arm, phase, gid, cart, p, pos, ans, pt, ca, dt, fr, cls=None):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "phase": phase, "gold": gid,
                                 "cart": cart, "pass": p, "pos": pos, "cls": cls,
                                 "ans": ans[:140], "ptok": pt, "eval": pt - ca,
                                 "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    for arm in ("D", "N"):
        for p in range(1, n_pass + 1):
            slot("restore", fname)
            conv = [{"role": "user", "content": lead}, {"role": "assistant", "content": ack}]
            pre = [(g[0], g[1], g[2]) for g in GOLDS[:26]] if arm == "D" \
                else [(None, None, f) for f in FILLERS]
            for i, (gid, cart, q) in enumerate(pre):        # 26 preamble turns
                ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": q + SUFFIX}])
                row(arm, "preamble", gid, cart, p, i, ans, pt, ca, dt, fr,
                    classify_u(ans, gid, NOVEL_VS) if gid else None)
                conv += [{"role": "user", "content": q + SUFFIX},
                         {"role": "assistant", "content": ans}]
            for i, (gid, cart, q, _) in enumerate(GOLDS):   # 30 test turns, identical positions
                ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": q + SUFFIX}])
                row(arm, "test", gid, cart, p, i, ans, pt, ca, dt, fr, classify_u(ans, gid, NOVEL_VS))
                conv += [{"role": "user", "content": q + SUFFIX},
                         {"role": "assistant", "content": ans}]
            print(f"arm {arm} pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(arm, lo=None, hi=None, cart=None):
        sel = [r for r in rows if r["arm"] == arm and r["phase"] == "test"
               and (lo is None or lo <= r["pos"] < hi)
               and (cart is None or r["cart"] == cart)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    def ptok_at(arm, pos):
        v = sorted(r["ptok"] for r in rows if r["arm"] == arm and r["phase"] == "test"
                   and r["pos"] == pos)
        return v[len(v) // 2] if v else 0

    d, dn = rate("D"); n, nn = rate("N")
    lines = [f"P5 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"temp=1.0 test-30 after 26 preamble turns (paired arms, identical positions)"]
    lines.append(f"  TEST recall: D (cart-answer history) {d:.3f} (n={dn}) | "
                 f"N (chit-chat history) {n:.3f} (n={nn}) | D-N {d-n:+.3f} "
                 f"| banked C30 no-suffix was 0.667")
    for lo, hi, lab in ((0, 10, "pos 1-10 "), (10, 20, "pos 11-20"), (20, 30, "pos 21-30")):
        dd, _ = rate("D", lo, hi); nn, _ = rate("N", lo, hi)
        lines.append(f"    {lab} D {dd:.3f} | N {nn:.3f}")
    for c in sorted({r["cart"] for r in rows if r["phase"] == "test" and r["cart"]}):
        dd, _ = rate("D", cart=c); nn, _ = rate("N", cart=c)
        lines.append(f"    cart {c:12s} D {dd:.3f} | N {nn:.3f}")
    lines.append(f"  size parity at test pos 30: D ptok {ptok_at('D', 29)} vs "
                 f"N ptok {ptok_at('N', 29)} (history sizes comparable if close)")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p5_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
