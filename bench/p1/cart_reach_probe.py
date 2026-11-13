#!/usr/bin/env python3
"""#3 — the reach probe: measure the 2,048-cell wall as a CURVE, per boot (2026-11-13).

The law on the books says a grafted read consults the FIRST 2,048 cells of a staged
prefix and nothing past them, even though the file holds every byte (2026-10-30,
`1,900 passes / 2,048 fails`). That is two points. This script measures the whole
inclusion curve, so every boot can say where the wall is TODAY instead of remembering
where it was. The cause is the architecture's selection budget — Qwen Sparse Attention
selects at the micro-block level with a stated budget of 512 blocks / 2,048 tokens
(fetched 2026-11-11 from the base card) — so the expected shape is a cliff at 2,048,
and the interesting data is what the cliff looks like in its neighbourhood.

Shape, and why this shape:
  FILLER is prose; FACTS are one-sentence claims with a unique codeword and a number,
  planted at target CELL positions (a cell = one prompt token, the unit the engine
  charges and the QSA budget counts). Positions are calibrated with the server's own
  token counter (POST /v1/messages/count_tokens), not with a chars/4 guess: the
  field-name law — measure with the instrument that produces the number.
  The staged prefix is a SAVED CONVERSATION, not a minted cart: `X-Strata-Carts-Graft`
  resolves any name in the slot vault (serve/test_cart_parity.py, 2026-11-05), so one
  chat completion + one `POST /slots/0?action=save` is the whole rig, and no 570 MB
  cart file is written. The graft arm is the same engine path a cart graft rides.
  Each probe asks for ONE fact. A grafted read whose selection budget reaches the
  fact's cell answers with its number; one that does not, answers from general prior —
  which is why the score keys on the planted number, not on the prose.

  .venv/bin/python bench/p1/cart_reach_probe.py --out bench/p1/cart-reach-2026-11-13.jsonl

Answers ride temp 1.0 (the owner's bench rule, 2026-10-25) with 3 repeats; a match is
the fact's number appearing in the answer. Rubric fixed BEFORE the run, countersigned
by the owner at approval of this script.
"""
import argparse
import json
import pathlib
import statistics
import time
import urllib.request

URL = "http://127.0.0.1:8005"

# Target cells RELATIVE to the end of the standing prefix, and the fact planted there.
# Six points straddle the wall: two well inside, one at the edge, three outside.
# "Cell" is the unit the graft consults — an offset into the RENDERED prompt, and the
# standing cart (~9.4k tokens of the five persona files, always.md) rides ahead of the
# ruler text. The script measures that offset live (count_tokens of one bare "ok"
# message) and plants at standing + target, so a HIT/miss names the wall's position in
# the units the engine charges.
FACTS = [
    (200,  "Vexholm",   "The Vexholm pipeline moves 41 barrels an hour."),
    (700,  "Kaldrun",   "Kaldrun island was charted in the year 617."),
    (1200, "Orrery",    "The Orrery clock loses 13 seconds a week."),
    (1900, "Sablewick", "Sablewick station has 27 platform lamps."),
    (2150, "Thornvale", "The Thornvale bridge spans 809 feet."),
    (2500, "Ashmere",   "Ashmere quarry yields 92 tonnes a day."),
]

FILLER = (
    "The ledger of the yard records each arrival by hour, and the clerk writes the "
    "count on a slate that is wiped at dusk. Carts arrive from the quarries in the "
    "hills, and the drivers rest at the tavern before the return climb. A tally "
    "kept honestly is worth more than a fast one, the old foreman used to say, "
    "because a wrong number outlives the man who wrote it. "
) * 60  # ~5.5k chars; the calibrator trims segments to hit the target cells


def count_tokens(text: str) -> int:
    body = {"model": "strata", "messages": [{"role": "user", "content": text}]}
    req = urllib.request.Request(URL + "/v1/messages/count_tokens",
                                 data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json",
                                          "anthropic-version": "2023-06-01",
                                          "X-Strata-Memory": "off"})   # calibrate in the
    # same coordinates the probe asks in: with the block riding, the count carries it too
    with urllib.request.urlopen(req, timeout=120) as r:
        return int(json.load(r).get("input_tokens") or 0)


def build_doc(base: int) -> tuple[str, dict]:
    """Concatenate filler segments and facts so each fact lands at its target cell of
    the GRAFT's window — cells counted from the end of the standing prefix, which
    rides ahead of the ruler in every prompt this server renders. count_tokens
    charges that prefix on every call, so the counter's own reading IS the coordinate
    (`n(doc) + n(seg) ≈ base + doc-relative + seg-relative`).

    Converge per segment on the measured count: grow/shrink the candidate filler by
    the measured ratio, 2-4 tries, tolerance ~6 tokens (~0.3% of the window)."""
    doc = ""
    landed = {}
    for wtarget, name, fact in FACTS:
        target = base + wtarget        # the counter charges the standing prefix on
        # every call, so a window cell T is prompt cell base+T: one coordinate system.
        n_doc = count_tokens(doc)
        seg = FILLER
        for _ in range(5):  # converge count_tokens(doc + seg) on the target cell
            n = count_tokens(doc + seg)
            if abs(n - target) <= 6:
                break
            seg_tok = max(n - n_doc, 1)
            want = max(target - n_doc, 1)
            seg = (FILLER * 40)[:max(40, int(len(seg) * (want / seg_tok)))]
        doc += seg.rstrip() + " " + fact + " "
        landed[name] = count_tokens(doc) - count_tokens(fact) - base  # graft-window cell
    doc += FILLER  # pad past the last fact so cell 2,700 exists
    return doc, landed


def ask(q: str, graft: str | None, max_tokens: int = 220) -> tuple[str, int, int]:
    # 220, not 64: this model reasons before it answers (reasoning_content), and a
    # 64-token budget bought 165 tokens of thinking and an empty content. The score
    # reads content + reasoning: the wall question is WHICH cells the read consults,
    # and a fact named in the reasoning was consulted.
    # X-Strata-Memory: off (memory.py:273) — with the store's block riding, the model
    # spends its budget calling memory_search instead of answering from the staged
    # prefix; the probe measures the prefix, so mute the block on both seed and probe.
    body = {"model": "strata", "messages": [{"role": "user", "content": q}],
            "max_tokens": max_tokens, "temperature": 1.0, "stream": False}
    req = urllib.request.Request(URL + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json",
                                          "X-Strata-Memory": "off"})
    if graft:
        req.add_header("X-Strata-Carts-Graft", graft)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.load(r)
    ms = round((time.perf_counter() - t0) * 1000)
    u = out.get("usage") or {}
    m = ((out.get("choices") or [{}])[0].get("message") or {})
    ans = (m.get("content") or "") + " " + (m.get("reasoning_content") or "")
    return ans.strip(), int(u.get("prompt_tokens") or 0), ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="reach-ruler-2700.bin",
                    help="vault file name the staged prefix is saved as (.bin appended)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default="")
    ap.add_argument("--skip-seed", action="store_true",
                    help="the prefix is already saved; probe only (a re-measure on the same boot)")
    ap.add_argument("--mint", default="",
                    help="mint this name as a CART from the ruler text and probe the cart arm "
                         "(needs memory.cartridges.minted); the saved-conversation arm is the default")
    ap.add_argument("--doc-file", default="/tmp/opencode/reach_ruler_doc.txt",
                    help="the ruler text is written here on a build run and read from here by --mint")
    a = ap.parse_args()
    out = open(a.out, "a") if a.out else None
    # The standing cart + template the seed turn rides: measured with the same counter
    # the graft arm's prompt is charged, so a "cell" here is the engine's unit.
    base = count_tokens("__probe__")

    doc, landed = build_doc(base)
    n_doc = count_tokens(doc)
    print(f"standing prefix: {base} cells (measured). doc: {n_doc} tokens, "
          f"facts planted at prompt cells {landed}", flush=True)
    pathlib.Path(a.doc_file).write_text(doc)
    graft_name = a.name
    if a.mint:
        body = json.dumps({"op": "mint", "name": a.mint, "force": True,
                           "sources": {"text": doc, "title": "reach ruler 2700"}}).encode()
        req = urllib.request.Request(URL + "/memory", data=body,
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            mr = json.load(r)
        print("mint:", json.dumps(mr.get("result") or mr)[:200], flush=True)
        graft_name = a.mint
    if not a.skip_seed:
        _, pt, ms = ask(doc, None, max_tokens=8)   # the seed turn: the prefix becomes slot 0
        print(f"seed turn: ptok={pt} {ms}ms", flush=True)
        # llama-server's shape: POST /slots/0?action=save {"filename": NAME} (server.py:5780)
        req = urllib.request.Request(URL + "/slots/0?action=save",
                                     data=json.dumps({"filename": a.name}).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            print("save:", json.load(r), flush=True)

    rows = []
    for rep in range(a.repeats):
        for target, name, fact in FACTS:
            q = f"In one short sentence, what does the record say about {name}? Give the number."
            ans, pt, ms = ask(q, graft_name)
            num = fact.split()[-1].rstrip(".")          # the planted number, the score key
            hit = num in ans
            r = {"rep": rep, "cell": landed.get(name, target), "fact": name,
                 "hit": hit, "ptok": pt, "ms": ms, "answer": ans[:140]}
            rows.append(r)
            print(f"rep{rep} cell{r['cell']:>5} {name:10s} {'HIT' if hit else 'miss':4s} "
                  f"ptok={pt} {ms}ms :: {ans[:60]!r}", flush=True)
            if out:
                out.write(json.dumps(r) + "\n"); out.flush()

    print("\n--- inclusion curve (3 repeats, hit rate by cell) ---", flush=True)
    for target, name, _ in FACTS:
        sub = [r for r in rows if r["fact"] == name]
        h = sum(1 for r in sub if r["hit"])
        print(f"cell {sub[0]['cell']:>5}  {name:10s} {h}/{len(sub)}", flush=True)
    inside = [r for r in rows if r["cell"] <= 2048]
    outside = [r for r in rows if r["cell"] > 2048]
    if inside and outside:
        print(f"inside(<=2048): {sum(r['hit'] for r in inside)}/{len(inside)}  "
              f"outside(>2048): {sum(r['hit'] for r in outside)}/{len(outside)}", flush=True)


if __name__ == "__main__":
    main()
