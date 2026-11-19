#!/usr/bin/env python3
"""pu_run - P-unique: Grok's falsification probe for the C-line (owner pasted the reply
2026-10-25). Four numeric golds of mam-test745 are replaced with UNIQUE low-frequency
nonces of identical role (eleven->XQ7K9M, 761-762->T3V8N2, 11/11->V6H2QT, eight->BR4LP2);
the six non-numeric golds ride UNCHANGED as in-body controls. Same questions, same
compose geometry, same restore protocol. NEW OWNER RULE from 2026-10-25: temp 1.0,
max_tokens 500, >=3 passes (the 0.8 bands of G3/P1 are historic; in-run C-ORIG10 re-baselines).
Decision rule: the rewritten set jumping to ~0.35+ while the control set stays flat =
distinctiveness is causal (the indexer keys on rarity); rewritten set still ~0.1 = the
problem is deeper (state capacity / indexer training / generation difficulty).
Records: /home/eugene/Strata-data/bench/p1/pu_<tag>/; never /tmp.
Run: .venv/bin/python spikes/cartridge/pu_run.py [--passes 3]
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, post, slot, norm, IDK, NUMTOK   # frozen instrument (geometry helpers)

BENCH = "/home/eugene/Strata-data/bench/p1"
HDR = [("X-Strata-Memory-Block", "off")]
STATE_LEAD = "Answer using only what you learned earlier. "
MAM = [g for g in GOLDS if g[1] == "mam-test745"]
REWRITTEN = {"t1": ["xq7k9m"], "t2": ["t3v8n2"], "t5": ["v6h2qt"], "t6": ["br4lp2"]}
VS_ORIG = {g: vs for g, _, _, vs in GOLDS}
VS_UNIQ = {g: REWRITTEN.get(g, vs) for g, vs in VS_ORIG.items()}


def hit(v, a):
    if v.startswith("\\b"):
        m = re.search(v, a)
        return m.start() if m else None
    if re.fullmatch(r"[\d.]+", v):
        try:
            val = float(v)
        except ValueError:
            m = re.search(rf"(?<![\d.]){re.escape(v)}(?!\d)", a)   # period-fix, as G3 Results
            return m.start() if m else None
        for m in NUMTOK.finditer(a):
            if abs(float(m.group()) - val) < 1e-9:
                return m.start()
        return None
    m = re.search(re.escape(v), a)
    return m.start() if m else None


def classify_u(ans, gid, vs):
    a = norm(ans)
    im = IDK.search(a)
    starts = [s for s in (hit(v, a) for v in vs[gid]) if s is not None]
    if starts and not (im and im.start() <= min(starts)):
        return "gold"
    return "idk" if im else "other"


def chat_u(messages):
    t0 = time.time()
    r = post("/v1/chat/completions", {"model": "m", "messages": messages, "temperature": 1.0,
                                      "max_tokens": 500, "reasoning_effort": "off",
                                      "tool_choice": "none"}, HDR)
    u = r.get("usage", {})
    det = u.get("prompt_tokens_details") or {}
    ch = r["choices"][0]
    ans = (ch["message"].get("content") or "").strip().replace("\n", " ")
    return ans, int(u.get("prompt_tokens") or 0), int(det.get("cached_tokens") or 0), \
        time.time() - t0, ch.get("finish_reason")


def lead_of(bodies):
    return ("You are about to learn three short notes carried as carts. Learn them; "
            "acknowledge with OK only.\n\n"
            + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in sorted(bodies)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=3)
    a = ap.parse_args()
    n_pass = a.passes

    standing = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
    assert standing, "no standing cart"
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    base = {n: carts[n]["sources"]["text"] for n in ("c4-results", "merge-notes")}
    bodies_o = dict(base, **{"mam-test745": carts["mam-test745"]["sources"]["text"]})
    bodies_u = dict(base, **{"mam-test745": open(os.path.join(HERE, "mam_unique.txt")).read().strip()})
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"pu_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "pu_rows.jsonl")
    rows_f = open(rows_path, "w")
    f_o, f_u = f"PU_ORIG_{tag}.bin", f"PU_UNIQ_{tag}.bin"

    def build(fname, bodies):
        slot("restore", standing)
        lead = lead_of(bodies)
        ack, pt, ca, dt, fr = chat_u([{"role": "user", "content": lead}])
        r = slot("save", fname)
        print(f"  compose {fname}: lead eval {pt - ca} tok, saved {r.get('n_saved')} rows",
              flush=True)
        return lead, ack

    lead_u, ack_u = build(f_u, bodies_u)
    build(f_o, bodies_o)

    def row(arm, conv, p, gid, ans, pt, ca, dt, fr, vs):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "conv": conv, "pass": p, "gold": gid,
                                 "set": "rewritten" if gid in REWRITTEN else "control",
                                 "cls": classify_u(ans, gid, vs), "ans": ans[:160],
                                 "ptok": pt, "eval": pt - ca, "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    def state_ask(arm, fname, p, gid, q, vs):
        slot("restore", fname)
        ans, pt, ca, dt, fr = chat_u([{"role": "user", "content": STATE_LEAD + q}])
        row(arm, 0, p, gid, ans, pt, ca, dt, fr, vs)

    for p in range(1, n_pass + 1):
        for gid, _, q, _ in MAM:
            state_ask("C-ORIG10", f_o, p, gid, q, VS_ORIG)
        for gid, _, q, _ in MAM:
            state_ask("C-UNIQ", f_u, p, gid, q, VS_UNIQ)
        for ci in range(0, len(MAM), 4):
            slot("restore", f_u)
            conv = [{"role": "user", "content": lead_u}, {"role": "assistant", "content": ack_u}]
            for gid, _, q, _ in MAM[ci:ci + 4]:
                ans, pt, ca, dt, fr = chat_u(conv + [{"role": "user", "content": q}])
                row("A-UNIQ", ci // 4, p, gid, ans, pt, ca, dt, fr, VS_UNIQ)
                conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def rate(arm, s=None):
        sel = [r for r in rows if r["arm"] == arm and (s is None or r["set"] == s)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    def med(arm):
        ev = sorted(r["eval"] for r in rows if r["arm"] == arm)
        return ev[len(ev) // 2] if ev else 0

    lines = [f"PU verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"passes={n_pass} temp=1.0 maxtok=500 block=off tool=off (owner rule 2026-10-25)"]
    for arm, note in (("C-ORIG10", "temp-1.0 baseline band (0.8 band was 0.07-0.20)"),
                      ("C-UNIQ", "the probe: nonces must jump vs C-ORIG10's rewritten set"),
                      ("A-UNIQ", "health: nonce cart text-riding must be high")):
        r_all, n = rate(arm)
        r_r, _ = rate(arm, "rewritten")
        r_c, _ = rate(arm, "control")
        lines.append(f"  {arm:8s} all {r_all:.3f} | REWRITTEN {r_r:.3f} (n={4*n_pass}) | "
                     f"control {r_c:.3f} (n={6*n_pass}) | med eval {med(arm)} tok | {note}")
    guard = med("A-UNIQ")
    lines.append(f"  GUARD: A-UNIQ median eval {guard} tok - "
                 + ("OK (compose cache honored)" if guard < 150 else "FLAG: alignment suspect"))
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"pu_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
