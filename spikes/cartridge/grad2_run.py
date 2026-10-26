#!/usr/bin/env python3
"""grad2_run - the anchor re-gate (2026-10-26): GRAD2_PRE_REG.md is the frozen contract,
this file is the frozen instrument. Runs on the boot that carries the anchor/tail build,
with the box configured block_position:"tail" + attach_mode:"anchor" (the banner must
SHOW both before the first ask - read it, do not assume it).

  N ANCHOR  X-Strata-Carts + X-Strata-Carts-Mode: anchor - bodies re-presented by the
            SERVER on every ask, ahead of the question, never in the client's history
            (arm B's 90/90 anchor effect without B's history bloat). The ship candidate.
  P PREFIX  same names, Mode: prefix - the S4a incumbent on the same cheap stack (tail
            recall), isolating what the per-ask anchor actually buys.
  C FLOOR   no carts, block OFF - persona gauge (overlap warning inherited from grad).

Conversation shape: the golds ARE the window's turns (30 per pass, 3 passes, temp
default, max_tokens 500, answer-phrase scorer with the period fix - all inherited
byte-for-byte from grad_run so the cross-run comparison holds; the one amendment, the
position-neutral ATTACH_LEAD, is logged in the pre-reg).

Verdict per the frozen gate: GRADUATE-ANCHOR iff N >= 0.95 overall AND N >= P + 0.02
AND no cart below 0.85 AND zero per-window collapses (a pass < 0.90). Buckets of med
eval tok are printed per arm - the anchor's flatness claim needs its own numbers.
bench/p1/grad2_<tag>/.
"""
import datetime
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from g3_run import GOLDS                                # noqa: E402
from pu_run import classify_u                           # noqa: E402

BENCH = "/home/eugene/Strata-data/bench/p1"
BASE = "http://127.0.0.1:8005"
CARTS = "c4-results,mam-test745,merge-notes"
NOVEL_VS = {g: vs for g, _, _, vs in GOLDS}
ARM_HDRS = {"N": {"X-Strata-Carts": CARTS, "X-Strata-Carts-Mode": "anchor"},
            "P": {"X-Strata-Carts": CARTS, "X-Strata-Carts-Mode": "prefix"},
            "C": {"X-Strata-Memory-Block": "off"}}
ARM_NAME = {"N": "ANCHOR", "P": "PREFIX", "C": "FLOOR"}
CRONS = ("c4-results", "mam-test745", "merge-notes")


def post(path, body=None):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def chat(msgs, hdrs=None):
    body = {"model": "m", "max_tokens": 500, "reasoning_effort": "off", "messages": msgs}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(hdrs or {})})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=600))
    u = d.get("usage", {})
    return (d["choices"][0]["message"]["content"] or "",
            int(u.get("prompt_tokens") or 0),
            int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            round(time.time() - t0, 2))


def main():
    n_pass = 3
    standing = post("/memory?limit=1", None)["stats"]["cartridges"]["file"]
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"grad2_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "grad2_rows.jsonl")
    rows_f = open(rows_path, "w")
    print(f"GRAD2 standing={standing} carts={CARTS}", flush=True)

    def row(arm, p, pos, gid, cart, ans, pt, ca, dt):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "pass": p, "pos": pos, "gold": gid,
                                 "cart": cart,
                                 "cls": classify_u(ans, gid, NOVEL_VS), "ans": ans[:140],
                                 "ptok": pt, "eval": pt - ca, "s": dt}) + "\n")
        rows_f.flush()

    for p in range(1, n_pass + 1):
        for arm in ("N", "P", "C"):
            conv = []
            for pos, (gid, cart, q, _) in enumerate(GOLDS):
                ans, pt, ca, dt = chat(conv + [{"role": "user", "content": q}], ARM_HDRS[arm])
                row(arm, p, pos, gid, cart, ans, pt, ca, dt)
                conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
            print(f"  pass {p} arm {arm} ({ARM_NAME[arm]}) done", flush=True)
    rows_f.close()

    rows = [json.loads(l) for l in open(rows_path)]

    def sel(arm, cart=None, p=None, lo=None, hi=None):
        return [r for r in rows if r["arm"] == arm and (cart is None or r["cart"] == cart)
                and (p is None or r["pass"] == p)
                and (lo is None or r["pos"] >= lo)
                and (hi is None or r["pos"] < hi)]

    def rate(arm, **kw):
        s = sel(arm, **kw)
        return (sum(1 for r in s if r["cls"] == "gold") / len(s), len(s)) if s else (0, 0)

    def medev(arm, **kw):
        ev = sorted(r["eval"] for r in sel(arm, **kw))
        return ev[len(ev) // 2] if ev else 0

    def perpass(arm):
        return [round(rate(arm, p=p)[0], 3) for p in (1, 2, 3)]

    n, nn = rate("N")
    p_ov, pn = rate("P")
    c_ov, cn = rate("C")
    n_passes = perpass("N")
    p_passes = perpass("P")
    cond = [n >= 0.95, n >= p_ov + 0.02,
            all(rate("N", cart=c)[0] >= 0.85 for c in CRONS),
            all(v >= 0.90 for v in n_passes)]
    gate = "GRADUATE-ANCHOR" if all(cond) else "NOT YET"

    def buckets(arm):
        # depth buckets by turn position (P10's shape): 1-8, 9-16, 17-24 of the 30-turn window
        return [medev(arm, lo=a, hi=b) for a, b in ((0, 8), (8, 16), (16, 24))]

    lines = [f"grad2 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"(GRAD2_PRE_REG.md gate: N>=0.95, N>=P+0.02, no cart <0.85, no pass <0.90)",
             f"  N ANCHOR {n:.3f} (n={nn}) | med eval {medev('N')} tok | buckets "
             + " ".join(map(str, buckets("N"))) + " | per-pass " + " ".join(map(str, n_passes))
             + " | carts: " + " ".join(f"{c.split('-')[0]} {rate('N', cart=c)[0]:.3f}" for c in CRONS),
             f"  P PREFIX {p_ov:.3f} (n={pn}) | med eval {medev('P')} tok | buckets "
             + " ".join(map(str, buckets("P"))) + " | per-pass " + " ".join(map(str, p_passes))
             + " | carts: " + " ".join(f"{c.split('-')[0]} {rate('P', cart=c)[0]:.3f}" for c in CRONS),
             f"  C FLOOR  {c_ov:.3f} (n={cn}) | med eval {medev('C')} tok (gauge only)",
             f"  gate legs: N>=0.95 {'PASS' if cond[0] else 'FAIL'} | N>=P+0.02 "
             f"{'PASS' if cond[1] else 'FAIL'} | carts>=0.85 {'PASS' if cond[2] else 'FAIL'} | "
             f"no N pass<0.90 {'PASS' if cond[3] else 'FAIL'}",
             f"  VERDICT: {gate}"]
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"grad2_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
