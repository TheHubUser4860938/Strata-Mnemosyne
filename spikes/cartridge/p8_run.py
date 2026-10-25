#!/usr/bin/env python3
"""p8_run - the C3 BAKE-OFF: depth countermeasures on the owner's home turf (2026-10-25).
Owner's fact: his real windows regularly run past 10-20 turns, so the decay P5/P6 measured
is a shipping problem, not a curiosity. Three arms ride the SAME deep geometry on one
3-cart compose file (f_r = standing + LEAD + ack, guard 7-10K rows):

  N (NONE)       bodies ride the compose front from turn 1 and never come back -
                 the in-run control; the decay curve predicts ~0.1 by zone 3.
  R (RE-ANCHOR)  bodies at front + re-presented as a tail REF round before each zone's
                 golds (P6's mechanism, extended to depth ~50).
  L (ROLL-UP)    the managed-scratchpad emulation: bodies at front, and the conversation
                 is kept as LEAD(+summary stub) + the last 10 messages - old chit-chat is
                 rolled up, so distance to the carts stays small. Caveat: the stub
                 discards old CONTENT; golds never need chit-chat content, so this
                 isolates DISTANCE - the variable C3 actually buys. The stub's counter
                 changes only at drop events, emulating boundary rewrites, ~3/zone.

Zones: the 26-turn P5/P6 chit-chat preamble, then three zones of 6 fillers + 3 golds
(test depths ~33 / ~42 / ~51 absolute; L's effective depth stays ~12). Fillers cycle
mod 26 past the preamble (at most one repeat each, logged). 3 passes, gold rotation
0-8 / 10-18 / 20-28, SUFFIX as P5/P6, temp 1.0, block off, tool off.
bench/p1/p8_<tag>/. The verdict feeds C3 directly: whichever arm holds zone 3 at the
cheaper eval cost is what the orchestration build ships.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot                        # noqa: E402
from pu_run import chat_u, classify_u                        # noqa: E402
from p5_run import FILLERS, SUFFIX                           # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
PRE, ZF, ZG = 26, 6, 3


def main():
    n_pass = 3
    standing = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    bodies = {n: carts[n]["sources"]["text"] for n in sorted(carts)}
    body_txt = "\n\n".join(f"[{n}]\n{bodies[n]}" for n in sorted(carts))
    LEAD = ("You are about to learn three short notes carried as carts. Learn them; "
            "acknowledge with OK only.\n\n" + body_txt)
    REF = "These three notes are available to you now:\n\n" + body_txt
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p8_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_f = open(os.path.join(out_dir, "p8_rows.jsonl"), "w")
    f_r = f"P8_R_{tag}.bin"
    slot("restore", standing)
    ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": LEAD}])
    r = slot("save", f_r)
    saved = r.get("n_saved") or 0
    print(f"P8 standing={standing} compose saved {saved} rows"
          + ("" if 7000 < saved < 10000 else "  FLAG: base suspect (want 7-10K)"),
          flush=True)

    def filler(j):
        return FILLERS[j % len(FILLERS)]

    def ask(rows_f, arm, phase, kind, conv, p, zone, gid=None, cart=None):
        msg = phase if kind == "ref" else phase + SUFFIX
        ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": msg}])
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "phase": kind, "gold": gid,
                                 "cart": cart, "pass": p, "zone": zone,
                                 "depth": len(conv) + 1,
                                 "cls": classify_u(ans, gid, NOVEL_VS) if gid else None,
                                 "ans": ans[:140], "ptok": pt, "eval": pt - ca,
                                 "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()
        conv += [{"role": "user", "content": msg}, {"role": "assistant", "content": ans}]
        return ans

    def run_simple(arm, reanchor):
        """N and R: full growing conversation on the compose file."""
        for p in range(1, n_pass + 1):
            slot("restore", f_r)
            conv = [{"role": "user", "content": LEAD},
                    {"role": "assistant", "content": ack}]
            for j in range(PRE):
                ask(rows_f, arm, filler(j), "preamble", conv, p, -1)
            for z in range(3):
                for k in range(ZF):
                    ask(rows_f, arm, filler(PRE + z * ZF + k), "preamble", conv, p, z)
                if reanchor:
                    ask(rows_f, arm, REF, "ref", conv, p, z)
                for gid, cart, q, _ in GOLDS[(p - 1) * 10 + z * ZG:
                                             (p - 1) * 10 + z * ZG + ZG]:
                    ask(rows_f, arm, q, "gold", conv, p, z, gid, cart)
            print(f"  {arm} pass {p}/{n_pass} done", flush=True)

    def run_rollup():
        """L: LEAD(+rolling stub) + last 10 messages kept; older turns dropped."""
        arm = "L"
        for p in range(1, n_pass + 1):
            slot("restore", f_r)
            tail, nrolled = [], 0

            def conv():
                stub = (f"\n\n[Summary: {nrolled} earlier turns of everyday small talk, "
                        "nothing needed later.]" if nrolled else "")
                return ([{"role": "user", "content": LEAD + stub},
                         {"role": "assistant", "content": ack}] + tail)

            def step(phase, kind, zone, gid=None, cart=None):
                nonlocal nrolled
                msg = phase if kind == "ref" else phase + SUFFIX
                c = conv()
                ans, pt2, ca2, dt2, fr2 = chat_u(c + [{"role": "user", "content": msg}])
                rows_f.write(json.dumps({"tag": tag, "arm": arm, "phase": kind,
                                         "gold": gid, "cart": cart, "pass": p,
                                         "zone": zone, "depth": len(c) + 1,
                                         "cls": classify_u(ans, gid, NOVEL_VS) if gid
                                         else None, "ans": ans[:140], "ptok": pt2,
                                         "eval": pt2 - ca2, "s": round(dt2, 2),
                                         "fr": fr2}) + "\n")
                rows_f.flush()
                tail.extend([{"role": "user", "content": msg},
                             {"role": "assistant", "content": ans}])
                if len(tail) > 10:
                    nrolled += len(tail) - 10
                    del tail[:-10]
            for j in range(PRE):
                step(filler(j), "preamble", -1)
            for z in range(3):
                for k in range(ZF):
                    step(filler(PRE + z * ZF + k), "preamble", z)
                for gid, cart, q, _ in GOLDS[(p - 1) * 10 + z * ZG:
                                             (p - 1) * 10 + z * ZG + ZG]:
                    step(q, "gold", z, gid, cart)
            print(f"  L pass {p}/{n_pass} done", flush=True)

    run_simple("N", False)
    run_simple("R", True)
    run_rollup()
    rows_f.close()

    rows = [json.loads(l) for l in open(os.path.join(out_dir, "p8_rows.jsonl"))]

    def rate(arm, zone=None):
        sel = [r for r in rows if r["arm"] == arm and r["phase"] == "gold"
               and (zone is None or r["zone"] == zone)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    def medev(arm):
        ev = sorted(r["eval"] for r in rows if r["arm"] == arm and r["phase"] == "gold")
        return ev[len(ev) // 2] if ev else 0

    lines = [f"P8 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} "
             f"tag={tag} temp=1.0 depth-countermeasure bake-off, zones at depths "
             f"~33/~42/~51 (L kept effective depth ~12)",
             f"  banked pairs: P5-N front-only 0.078 (turns 27-56) | P6-R 0.167 | "
             f"fresh ceiling 0.933"]
    for arm, note in (("N", "NONE     (control: front carts, no countermeasure)"),
                      ("R", "RE-ANCHOR(tail REF before each zone's golds)"),
                      ("L", "ROLL-UP  (summary stub + last 10 msgs)")):
        a, n = rate(arm)
        z1, _ = rate(arm, 0); z2, _ = rate(arm, 1); z3, _ = rate(arm, 2)
        lines.append(f"  {arm} {note}: overall {a:.3f} (n={n}) | zones "
                     f"{z1:.3f}/{z2:.3f}/{z3:.3f} | med gold-ask eval {medev(arm)} tok")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p8_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
