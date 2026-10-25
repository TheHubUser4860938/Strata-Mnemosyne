#!/usr/bin/env python3
"""grad_run - the graduation A/B (2026-10-25 night): GRAD_PRE_REG.md is the frozen contract,
this file is the frozen instrument. Production attach over the wire vs naive per-ask text
vs the floor. Same boot, one engine generation, 30 golds x 3 passes x 3 arms, temp default
(the owner's bench rule), max_tokens 500, answer-phrase scorer.

  A ATTACH  X-Strata-Carts header on every request; bodies ride the prefix once and the
            conversation cache absorbs them (the S4a product shape).
  B TEXT    no header; every ask carries the identical body bytes re-pasted into its user
            message (the naive alternative; the evening banked its cost at ~1.5K/ask).
  C FLOOR   no header, no text, tier-3 block OFF (X-Strata-Memory-Block: off) - what the
            standing persona alone recalls. Gauge, not gate leg (persona overlap warning
            in the pre-reg: always.md quotes the C4 numbers).

Conversation shape: the golds ARE the window's turns (no preamble, no suffix - production
bytes, which is what G3's bench geometry could not claim). Verdict per the frozen gate:
graduate iff overall A >= B - 0.02 AND no cart collapses (A_cart < B_cart - 0.15).
bench/p1/grad_<tag>/.
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
    carts = {c["name"]: c for c in post("/memory", {"op": "carts"})["carts"]
             if c["name"] != "standing"}
    order = sorted(carts)
    TEXT = ("The notes below ride on this conversation's prefix as learned carts. They are "
            "given knowledge: use them, do not re-learn them, do not restate them.\n\n"
            + "\n\n".join(f"[{n}]\n{carts[n]['sources']['text']}" for n in order))
    standing = post("/memory?limit=1", None)["stats"]["cartridges"]["file"]
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, f"grad_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "grad_rows.jsonl")
    rows_f = open(rows_path, "w")
    print(f"GRAD standing={standing} carts={order} text_block={len(TEXT):,} chars", flush=True)

    def row(arm, p, gid, cart, ans, pt, ca, dt):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "pass": p, "gold": gid, "cart": cart,
                                 "cls": classify_u(ans, gid, NOVEL_VS), "ans": ans[:140],
                                 "ptok": pt, "eval": pt - ca, "s": dt}) + "\n")
        rows_f.flush()

    for p in range(1, n_pass + 1):
        for arm in ("A", "B", "C"):
            conv = []
            for i, (gid, cart, q, _) in enumerate(GOLDS):
                if arm == "A":
                    msg, hdrs = q, {"X-Strata-Carts": CARTS}
                elif arm == "B":
                    msg, hdrs = TEXT + "\n\n" + q, None
                else:
                    msg, hdrs = q, {"X-Strata-Memory-Block": "off"}
                ans, pt, ca, dt = chat(conv + [{"role": "user", "content": msg}], hdrs)
                row(arm, p, gid, cart, ans, pt, ca, dt)
                conv += [{"role": "user", "content": msg},
                         {"role": "assistant", "content": ans}]
            print(f"  pass {p} arm {arm} done", flush=True)
    rows_f.close()

    rows = [json.loads(l) for l in open(rows_path)]

    def rate(arm, cart=None):
        sel = [r for r in rows if r["arm"] == arm and (cart is None or r["cart"] == cart)]
        return (sum(1 for r in sel if r["cls"] == "gold") / len(sel), len(sel)) if sel else (0, 0)

    def medev(arm):
        ev = sorted(r["eval"] for r in rows if r["arm"] == arm)
        return ev[len(ev) // 2] if ev else 0

    a, na = rate("A")
    b, nb = rate("B")
    gate = "GRADUATE" if (a >= b - 0.02 and all(
        rate("A", c)[0] >= rate("B", c)[0] - 0.15 for c in ("c4-results", "mam-test745",
                                                            "merge-notes"))) else "NOT YET"
    lines = [f"graduation verdict @{datetime.datetime.now().isoformat(timespec='seconds')} "
             f"tag={tag} (GRAD_PRE_REG.md gate: A >= B - 0.02 overall, no cart below B - 0.15)",
             f"  A ATTACH {a:.3f} (n={na}) | med eval {medev('A')} tok | carts: "
             + " ".join(f"{c.split('-')[0]} {rate('A', c)[0]:.3f}"
                        for c in ("c4-results", "mam-test745", "merge-notes")),
             f"  B TEXT   {b:.3f} (n={nb}) | med eval {medev('B')} tok | carts: "
             + " ".join(f"{c.split('-')[0]} {rate('B', c)[0]:.3f}"
                        for c in ("c4-results", "mam-test745", "merge-notes")),
             f"  C FLOOR  {rate('C')[0]:.3f} (n={rate('C')[1]}) | med eval {medev('C')} tok "
             f"(gauge only - persona overlap warning in the pre-reg)",
             f"  VERDICT: {gate}"]
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"grad_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
