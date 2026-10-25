#!/usr/bin/env python3
"""p1_run - the content-shape probe (journal 2026-10-25, lever P1): does re-minting the
number-dense mam-test745 body as NARRATIVE PROSE lift the state-only (arm C) recall toward
the narrative cart's level (merge-notes 0.433 vs mam 0.100, corrected, G3 tag 122759)?

Single variable = body style. Same golds, questions, geometry, temp, and the frozen
scorer (g3_run.classify); the period-corrected scorer (G3 Results addendum) reports
alongside. Arms:
  C-ORIG   compose [c4-results | mam-test745 | merge-notes] built from the ledger
           bodies; mam's 10 golds asked state-only (restore per gold). In-run
           replication of G3 arm C - the control that makes the pair same-day.
  C-PROSE  same compose with mam's slot replaced by mam_prose.txt; same 30 asks. The probe.
  A-PROSE  prose compose, bodies re-sent as text in conversations (cart-health control:
           a prose cart must read at ~G3-A level or the rewrite broke the facts).
Alignment guard: A-PROSE median eval must stay under 150 tok (compose cache honored) -
flagged, never silently. Length confound (prose ~110% of original) printed at start.
3 passes, temp 0.8, X-Strata-Memory-Block: off, tool_choice none (inherited from g3_run.chat).
Records: /home/eugene/Strata-data/bench/p1/p1_<tag>/; never /tmp.

Run: .venv/bin/python spikes/cartridge/p1_run.py [--passes 3] [--smoke]
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS, classify, chat, post, slot, norm, IDK, NUMTOK   # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
HDR = [("X-Strata-Memory-Block", "off")]
STATE_LEAD = "Answer using only what you learned earlier. "
MAM_GOLDS = [g for g in GOLDS if g[1] == "mam-test745"]
GOLD_VS = {g: vs for g, _, _, vs in GOLDS}


def corrected_hit(ans, gid):
    r"""The period-fix scorer (G3 Results addendum): version lookahead (?!\d), not (?![\d.])."""
    a = norm(ans)
    im = IDK.search(a)
    for v in GOLD_VS[gid]:
        start = None
        if v.startswith("\\b"):
            m = re.search(v, a)
            start = m.start() if m else None
        elif re.fullmatch(r"[\d.]+", v):
            try:
                val = float(v)
            except ValueError:
                val = None
            if val is not None:
                for m in NUMTOK.finditer(a):
                    if abs(float(m.group()) - val) < 1e-9:
                        start = m.start()
                        break
            else:
                m = re.search(rf"(?<![\d.]){re.escape(v)}(?!\d)", a)
                start = m.start() if m else None
        else:
            m = re.search(re.escape(v), a)
            start = m.start() if m else None
        if start is not None and not (im and im.start() <= start):
            return True
    return False


def lead_of(bodies, mam_pos="middle"):
    order = sorted(bodies)
    if mam_pos == "last":   # P1b: recency confound - mam's body moved to the final slot
        order = [n for n in order if n != "mam-test745"] + ["mam-test745"]
    return ("You are about to learn three short notes carried as carts. Learn them; "
            "acknowledge with OK only.\n\n"
            + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in order))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--order", choices=("middle", "last"), default="middle",
                    help="mam body slot in the compose: ledger order (middle) or final (P1b)")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    golds = MAM_GOLDS[:2] if a.smoke else MAM_GOLDS
    n_pass = 1 if a.smoke else a.passes

    st = post("/memory?limit=1", None, [])["stats"]
    standing = (st.get("cartridges") or {}).get("file")
    assert standing, "no standing cart - P1 runs with the cartridge system on"
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    orig = {n: carts[n]["sources"]["text"] for n in ("c4-results", "mam-test745", "merge-notes")}
    prose = dict(orig)
    prose["mam-test745"] = open(os.path.join(HERE, "mam_prose.txt")).read().strip()
    print(f"P1 standing={standing} prose body={len(prose['mam-test745']):,} chars vs "
          f"orig={len(orig['mam-test745']):,} (length confound: {len(prose['mam-test745'])/len(orig['mam-test745']):.2f}x)",
          flush=True)

    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"p1_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "p1_rows.jsonl")
    rows_f = open(rows_path, "w")
    f_orig, f_prose = f"P1_ORIG_{tag}.bin", f"P1_PROSE_{tag}.bin"

    def build(fname, bodies):
        slot("restore", standing)
        lead = lead_of(bodies, a.order)
        ack, pt, ca, dt, fr = chat([{"role": "user", "content": lead}], HDR)
        r = slot("save", fname)
        print(f"  compose {fname}: lead eval {pt - ca} tok, saved {r.get('n_saved')} rows",
              flush=True)
        return lead, ack

    lead_p, ack_p = build(f_prose, prose)          # lead_p is the A-PROSE conversation head
    build(f_orig, orig)                            # C-ORIG needs no ack (state-only asks)

    def row(arm, conv, p, gid, q, ans, pt, ca, dt, fr):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "conv": conv, "pass": p, "gold": gid,
                                 "cart": "mam-test745", "ask": q, "cls": classify(ans, gid),
                                 "cls_corr": corrected_hit(ans, gid), "ans": ans[:160],
                                 "ptok": pt, "eval": pt - ca, "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()

    def state_ask(arm, fname, p, gid, q):
        slot("restore", fname)
        ans, pt, ca, dt, fr = chat([{"role": "user", "content": STATE_LEAD + q}], HDR)
        row(arm, 0, p, gid, q, ans, pt, ca, dt, fr)

    for p in range(1, n_pass + 1):
        for gid, _, q, _ in golds:
            state_ask("C-ORIG", f_orig, p, gid, q)
        for gid, _, q, _ in golds:
            state_ask("C-PROSE", f_prose, p, gid, q)
        for ci in range(0, len(golds), 4):
            slot("restore", f_prose)
            conv = [{"role": "user", "content": lead_p}, {"role": "assistant", "content": ack_p}]
            for gid, _, q, _ in golds[ci:ci + 4]:
                ans, pt, ca, dt, fr = chat(conv + [{"role": "user", "content": q}], HDR)
                row("A-PROSE", ci // 4, p, gid, q, ans, pt, ca, dt, fr)
                conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        print(f"pass {p}/{n_pass} done", flush=True)

    rows_f.close()
    rows = [json.loads(l) for l in open(rows_path)]

    def med(arm):
        ev = sorted(r["eval"] for r in rows if r["arm"] == arm)
        return ev[len(ev) // 2] if ev else 0

    lines = [f"P1 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"passes={n_pass} golds={len(golds)}/arm mam_pos={a.order} temp=0.8 block=off tool=off"]
    ref = {"C-ORIG": "G3 arm C mam: raw 0.067 / corrected 0.100 | narrative merge: 0.433",
           "C-PROSE": "target: narrative level ~0.43 if content-shape is the driver",
           "A-PROSE": "cart health: G3 arm A level ~0.90-0.97 expected"}
    for arm in ("C-ORIG", "C-PROSE", "A-PROSE"):
        sel = [r for r in rows if r["arm"] == arm]
        raw = sum(1 for r in sel if r["cls"] == "gold") / len(sel)
        corr = sum(1 for r in sel if r["cls_corr"]) / len(sel)
        abst = sum(1 for r in sel if IDK.search(norm(r["ans"]))) / len(sel)
        lines.append(f"  {arm:8s} raw {raw:.3f} | corrected {corr:.3f} | abstains {abst:.3f} "
                     f"| median eval {med(arm)} tok | {ref[arm]}")
    guard = med("A-PROSE")
    lines.append(f"  GUARD: A-PROSE median eval {guard} tok - "
                 + ("OK (compose cache honored)" if guard < 150 else "FLAG: alignment suspect"))
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"p1_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
