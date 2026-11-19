#!/usr/bin/env python3
"""p6_run - the PLACEMENT ladder (2026-10-25): does the owner's on-demand reframe fix
the positional decay? Same golds, same temp 1.0 rule, same 26-turn chit-chat preamble
as P5; only WHERE and WHEN the bodies enter changes. bench/p1/p6_<tag>/.

  P5-N control (banked): bodies at the FRONT from turn 1, tested turns 27-56 .... 0.078
  T  (PULL27)   bodies absent until a REFERENCE turn at 27, then ride in prefix -
                the on-demand pattern: pay ~1.6K once, at the tail, when needed.
  R  (REANCHOR) bodies at the front AND re-presented near the tail every 10 test
                turns (turns 27, 37, 47) - the hygiene rule: ~1.6K per anchor,
                ~165/ask amortized.

If T lands well above 0.078, placement (not the cartridge) is confirmed as the whole
story and on-demand pull is a free lunch worth its ~1.6K. If R approaches the A4Q
ceiling (0.933), re-anchor cadence 10 is the S4 constant. 3 passes, suffix as P5,
block off, tool off.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot                        # noqa: E402
from pu_run import chat_u, classify_u, HDR                  # noqa: E402
from p5_run import FILLERS, SUFFIX                          # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}


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
    out_dir = os.path.join(BENCH, f"p6_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p6_rows.jsonl")
    rows_f = open(rows_path, "w")
    print(f"P6 standing={standing} passes={n_pass} placement ladder", flush=True)

    # compose file for the R arm's front-riding bodies (guard: n_saved < 10K)
    f_r = f"P6_R_{tag}.bin"
    slot("restore", standing)
    ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": LEAD}])
    r = slot("save", f_r)
    saved = r.get("n_saved") or 0
    print(f"  compose R: saved {saved} rows"
          + ("" if 7000 < saved < 10000 else "  FLAG: base corrupt (want 7-10K; floor catches the no-persona slot that poisoned p6_152548)!"),
          flush=True)

    def row(arm, phase, gid, cart, p, pos, ans, pt, ca, dt, fr, cls=None):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "phase": phase, "gold": gid,
                                 "cart": cart, "pass": p, "pos": pos, "cls": cls,
                                 "ans": ans[:140], "ptok": pt, "eval": pt - ca,
                                 "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    def say(arm, phase, conv, p, pos, gid=None, cart=None):
        kind, txt = phase
        msg = txt if kind == "ref" else txt + SUFFIX      # fillers carry P5's suffix too (pairing)
        ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": msg}])
        cls = classify_u(ans, gid, NOVEL_VS) if gid else None
        row(arm, kind, gid, cart, p, pos, ans, pt, ca, dt, fr, cls)
        conv += [{"role": "user", "content": msg}, {"role": "assistant", "content": ans}]
        return ans

    for p in range(1, n_pass + 1):
        # T: no bodies until REF at turn 27 (persona-only state under the session)
        slot("restore", standing)
        conv = []
        for i, f in enumerate(FILLERS):
            say("T", ("preamble", f), conv, p, i)
        say("T", ("ref", REF), conv, p, 0)
        for i, (gid, cart, q, _) in enumerate(GOLDS):
            say("T", ("gold", q), conv, p, i, gid, cart)
        # R: bodies at the front AND re-anchored near the tail every 10 test turns
        slot("restore", f_r)
        conv = [{"role": "user", "content": LEAD}, {"role": "assistant", "content": ack}]
        for i, f in enumerate(FILLERS):
            say("R", ("preamble", f), conv, p, i)
        for i, (gid, cart, q, _) in enumerate(GOLDS):
            if i in (0, 10, 20):
                say("R", ("ref", REF), conv, p, i)
            say("R", ("gold", q), conv, p, i, gid, cart)
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(arm, lo=None, hi=None):
        sel = [r for r in rows if r["arm"] == arm and r["phase"] == "gold"
               and (lo is None or lo <= r["pos"] < hi)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    def medev(arm):
        ev = sorted(r["eval"] for r in rows if r["arm"] == arm and r["phase"] == "gold")
        return ev[len(ev) // 2] if ev else 0

    lines = [f"P6 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"temp=1.0 placement ladder (P5-N front-only control was 0.078; A4Q fresh ceiling 0.933)"]
    for arm, note in (("T", "bodies PULLED at turn 27 (on-demand pattern)"),
                      ("R", "front bodies + RE-ANCHOR every 10 test turns")):
        a, n = rate(arm)
        b1, _ = rate(arm, 0, 10); b2, _ = rate(arm, 10, 20); b3, _ = rate(arm, 20, 30)
        lines.append(f"  {arm} {note}: {a:.3f} (n={n}) | buckets {b1:.3f}/{b2:.3f}/{b3:.3f} "
                     f"| med gold-ask eval {medev(arm)} tok")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p6_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
