#!/usr/bin/env python3
"""p2_run - the PRIOR-FLOOR experiment (owner's data-type question, 2026-10-25).

Two confounds the C-line never quantified, settled in one run at the new bench rule
(temp 1.0, max_tokens 500, 3 passes, block off, tool off; bench/p1/p2_<tag>/):

PHASE 1 GUESS - all 30 novel G3 golds asked against the STANDING-ONLY state (no cart
bodies ever composed). Every C-line ask rode with the persona as standing prefix, and
always.md LITERALLY CONTAINS some gold answers (0.1.50, v0.2.5, 07:55, "100 and 500",
0.996, 15.6). This measures the floor: how much every gold is answerable from persona
text + weights with no cart at all. C-line minus this floor = the real state read.

PHASE 2 WORLD-CART / PHASE 3 WORLD-BARE - the owner's Cecil question directly: 10
capital-city golds (prior-consistent world knowledge), asked once against a composed
geography-note cart and once against standing-only. If WORLD-CART ~= WORLD-BARE ~= high,
world-consistent golds answer from the weights and inflate any "state-only read" claim
(their verification was structural - SHA/tensor - not prior-controlled). If WORLD-CART
clears WORLD-BARE, prior-consistent content genuinely reads better from state.

Geometry note: standing-only asks re-eval index+question (~90 tok, the index line is not
in the standing rows) vs ~45 tok in compose geometry - reported, expected, not a fault.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot, norm, IDK          # noqa: E402
from pu_run import chat_u, classify_u, STATE_LEAD, HDR   # noqa: E402  (temp 1.0 chat)

BENCH = "/home/eugene/Strata-data/bench/p1"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
CART_OF = {g: c for g, c, _, _ in GOLDS}
WORLD = [
    ("w1", "According to the geography note: what is the capital of France?", ["paris"]),
    ("w2", "According to the geography note: what is the capital of Japan?", ["tokyo"]),
    ("w3", "According to the geography note: what is the capital of Egypt?", ["cairo"]),
    ("w4", "According to the geography note: what is the capital of Kenya?", ["nairobi"]),
    ("w5", "According to the geography note: what is the capital of Canada?", ["ottawa"]),
    ("w6", "According to the geography note: what is the capital of Peru?", ["lima"]),
    ("w7", "According to the geography note: what is the capital of Thailand?", ["bangkok"]),
    ("w8", "According to the geography note: what is the capital of Poland?", ["warsaw"]),
    ("w9", "According to the geography note: what is the capital of Morocco?", ["rabat"]),
    ("w10", "According to the geography note: what is the capital of Turkey?", ["ankara"]),
]
WORLD_VS = {g: vs for g, _, vs in WORLD}
GEO = ("A geography note for a memory probe, compiled from world almanac entries. "
       "France's capital is Paris. Japan's capital is Tokyo. Egypt's capital is Cairo. "
       "Kenya's capital is Nairobi. Canada's capital is Ottawa. Peru's capital is Lima. "
       "Thailand's capital is Bangkok. Poland's capital is Warsaw. Morocco's capital is "
       "Rabat. Turkey's capital is Ankara - a city many visitors mistake for Istanbul. "
       "The note lists one capital per country and no other facts.")
GEO_LEAD = ("You are about to learn a short note carried as a cart. Learn it; "
            "acknowledge with OK only.\n\n[geo-note]\n" + GEO)


def main():
    n_pass = 3
    standing = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
    assert standing, "no standing cart"
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p2_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p2_rows.jsonl")
    rows_f = open(rows_path, "w")
    f_geo = f"P2_GEO_{tag}.bin"
    print(f"P2 standing={standing} (floor + world phases), passes={n_pass}, temp=1.0", flush=True)

    def row(phase, gid, cart, p, ans, pt, ca, dt, fr, vs):
        rows_f.write(json.dumps({"tag": tag, "phase": phase, "gold": gid, "cart": cart,
                                 "pass": p, "cls": classify_u(ans, gid, vs), "ans": ans[:160],
                                 "ptok": pt, "eval": pt - ca, "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    def bare(phase, p, gid, q, cart, vs):
        slot("restore", standing)
        ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
        row(phase, gid, cart, p, ans, pt, ca, dt, fr, vs)

    # compose the geo cart (single-body compose; size noted in verdict)
    slot("restore", standing)
    ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": GEO_LEAD}])
    r = slot("save", f_geo)
    print(f"  compose {f_geo}: lead eval {pt - ca} tok, saved {r.get('n_saved')} rows, ack {ack[:16]!r}",
          flush=True)

    for p in range(1, n_pass + 1):
        for gid, _, q, _ in GOLDS:                      # PHASE 1: the prior floor
            bare("GUESS", p, gid, q, CART_OF[gid], NOVEL_VS)
        for gid, q, _ in WORLD:                          # PHASE 2: world golds WITH cart
            slot("restore", f_geo)
            ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
            row("WORLD-CART", gid, "world", p, ans, pt, ca, dt, fr, WORLD_VS)
        for gid, q, _ in WORLD:                          # PHASE 3: world golds, no cart
            bare("WORLD-BARE", p, gid, q, "world", WORLD_VS)
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(phase, cart=None):
        sel = [r for r in rows if r["phase"] == phase and (cart is None or r["cart"] == cart)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    lines = [f"P2 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"passes={n_pass} temp=1.0 maxtok=500 block=off tool=off standing={standing}"]
    f_all, _ = rate("GUESS")
    lines.append(f"  GUESS floor, novel golds, NO cart: {f_all:.3f} (n=90) | "
                 + " ".join(f"{c.split('-')[0]}={rate('GUESS', c)[0]:.3f}"
                            for c in ("c4-results", "mam-test745", "merge-notes")))
    wc, _ = rate("WORLD-CART"); wb, _ = rate("WORLD-BARE")
    lines.append(f"  WORLD-CART {wc:.3f} (n=30) | WORLD-BARE {wb:.3f} (n=30) | "
                 f"delta {wc - wb:+.3f} (prior-consistent data: cart adds what?)")
    lines.append("  per-gold floor hits (gold answered correctly with NO cart):")
    hits = {}
    for r in rows:
        if r["phase"] == "GUESS" and r["cls"] == "gold":
            hits.setdefault(r["gold"], []).append(r["ans"][:60])
    for gid, n in sorted(hits.items(), key=lambda kv: kv[0]):
        lines.append(f"    {gid} ({CART_OF[gid]}) {len(n)}/3 :: {n[0]}")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p2_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
