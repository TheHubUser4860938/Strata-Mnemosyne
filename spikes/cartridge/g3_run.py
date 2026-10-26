#!/usr/bin/env python3
"""g3_run - Gate 3: composed carts against per-turn text injection (G3_PRE_REG.md, countersigned).

Arms (the contract, verbatim in shape):
  A COMPOSE    - the slot restores one pre-composed file per conversation (standing rows + the
                 LEAD message + the three cart bodies + ack); the conversation re-sends those
                 same bytes every turn, so the bodies ride as TEXT at ZERO compute (prefix
                 cache). The ship-able arm: the gate is A >= 0.9 x B recall, A's steady-state
                 eval tokens near the question's own.
  B INJECT     - the same conversations with the bodies appended AFTER the conversation as a
                 block each turn (re-evaluated, no compose). The control; the token tax made
                 visible in the eval column.
  C STATE-ONLY - compose restored, the question asked with the bodies NEVER re-sent
                 (the morning probe's geometry, S3-instruct shape). Research line: reported.

30 marker golds (10 per cart, the countersigned addendum), interleaved round-robin so
conversations mix carts, 8 conversations, 3 passes, temp 0.8, X-Strata-Memory-Block: off
(the block is query-variable text and has no place in a cart-vs-text comparison; the
tool-schema bytes ride every arm alike and stay cached behind the standing prefix).
Guards: standing-file invariant per conversation (the no-rotation clause), geometry rows
(prompt/eval/cached per ask), the foreign control (merge-notes' "zero" asked against a
compose that EXCLUDES merge-notes). Records: bench/g3/<tag>/; never /tmp.

Run: .venv/bin/python spikes/cartridge/g3_run.py [--passes 3] [--smoke]
"""
import argparse, datetime, json, os, re, sys, time, unicodedata, urllib.request

URL = "http://127.0.0.1:8005"
BENCH = "/home/eugene/Strata-data/bench/g3"

def norm(s):
    s = unicodedata.normalize("NFD", str(s)).lower()
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace(",", "").replace(" ", " ")

IDK = re.compile(r"\b(i don'?t know|do not know|does not (say|mention|specify|contain|provide)"
                 r"|not (sure|mentioned|specified|provided|available|in the|stated|present)"
                 r"|no (information|mention|data)|cannot|can'?t (answer|determine|provide)"
                 r"|unable to|not have (access|information)|don'?t have (access|information)"
                 r"|no prior context|not given)\b")

# gold id -> (cart, ask, [exact-marker variants, normalized]) - the countersigned table.
GOLDS = [
    ("t1",  "mam-test745", "According to the MAM Silicon Hippocampus reference note: how many physical cartridges did TEST745 build?", ["11", "eleven"]),
    ("c1",  "c4-results",  "According to the C4 bank-capacity verdict note: what was the mean recall at the 25-fact rung of the ladder?", ["1.000", "1.0"]),
    ("m1",  "merge-notes", "According to the upstream merge notes: which upstream version was merged on 2026-10-25?", ["0.2.5"]),
    ("t2",  "mam-test745", "According to the MAM reference note: how many body tokens does cartridge C01 carry?", ["761"]),
    ("c2",  "c4-results",  "According to the C4 verdict note: what was the mean recall at the 500-fact rung?", ["0.916"]),
    ("m2",  "merge-notes", "According to the upstream merge notes: what is the upstream merge commit hash for v0.2.5?", ["8c19ef9a"]),
    ("t3",  "mam-test745", "According to the MAM reference note: what GPU model ran TEST745?", ["a100"]),
    ("c3",  "c4-results",  "According to the C4 verdict note: what was the mean recall at the 1000-fact rung?", ["0.809"]),
    ("m3",  "merge-notes", "According to the upstream merge notes: how many serve/ files did v0.2.5 touch?", ["zero", r"\b0\b", "none", "no serve"]),
    ("t4",  "mam-test745", "According to the MAM reference note: is synthesis between cartridges direct tensor fusion?", ["text-mediated", "not direct", r"\bno\b"]),
    ("c4",  "c4-results",  "According to the C4 verdict note: what did the row-16 contract miss answer, where the gold had asked for D56?", ["y51"]),
    ("m4",  "merge-notes", "According to the upstream merge notes: what engine version did the rebuild from the fork's own tree produce?", ["0.1.50"]),
    ("t5",  "mam-test745", "According to the MAM reference note: what was the independent post-run cartridge verification score?", ["11/11"]),
    ("c5",  "c4-results",  "According to the C4 verdict note: how many distractor answers appeared at the 1000-fact rung?", ["96"]),
    ("m5",  "merge-notes", "According to the upstream merge notes: what BUILD.json src hash did the rebuilt engine record?", ["5944ca5d"]),
    ("t6",  "mam-test745", "According to the MAM reference note: how many text-mediated review rounds ran before the blind master?", ["8", "eight"]),
    ("c6",  "c4-results",  "According to the C4 verdict note: what leak baseline rate was declared at the 100-fact rung?", ["0.06"]),
    ("m6",  "merge-notes", "According to the upstream merge notes: which script was the third victim of the pack-script rename?", ["update.sh"]),
    ("t7",  "mam-test745", "According to the MAM reference note: what is the status of human expert grading of the blind answers?", ["pending"]),
    ("c7",  "c4-results",  "According to the C4 verdict note: between which rungs of the ladder was the ceiling declared?", ["100 and 500"]),
    ("m7",  "merge-notes", "According to the upstream merge notes: which commit fixed the README version caption?", ["f77702da"]),
    ("t8",  "mam-test745", "According to the MAM reference note: name the researcher who runs the AKBASCORE programme.", ["akbas"]),
    ("c8",  "c4-results",  "According to the C4 verdict note: what composed recall did the k=5 attach reach?", ["0.996"]),
    ("m8",  "merge-notes", "According to the upstream merge notes: at what time did the green post-merge audit boot stand?", ["07:55"]),
    ("t9",  "mam-test745", "According to the MAM reference note: which cartridge was the sealed BLIND master?", ["c11"]),
    ("c9",  "c4-results",  "According to the C4 verdict note: what fixed MB per state file did the economics fit report as its intercept?", ["236.1"]),
    ("m9",  "merge-notes", "According to the upstream merge notes: which version was merged first, by tag, on 2026-10-24?", ["0.2.4.2"]),
    ("t10", "mam-test745", "According to the MAM reference note: which indexing answered their selection prior art in TEST610 and 642?", ["faiss", "pca"]),
    ("c10", "c4-results",  "According to the C4 verdict note: what marginal cost per standing token did the economics fit report?", ["15.6"]),
    ("m10", "merge-notes", "According to the upstream merge notes: which branch carries all of this work?", ["memory-core"]),
]
ALL_MARKERS = [v for _, _, _, vs in GOLDS for v in vs]

def post(path, body=None, headers=(), tries=2):
    data = json.dumps(body).encode() if body is not None else None
    for a in range(tries):
        try:
            req = urllib.request.Request(URL + path, data=data,
                                         headers={"Content-Type": "application/json", **dict(headers)})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except Exception:
            if a + 1 == tries:
                raise
            time.sleep(1.5)

def slot(action, fname):
    return post(f"/slots/0?action={action}", {"filename": fname})

def chat(messages, headers):
    t0 = time.time()
    r = post("/v1/chat/completions", {"model": "m", "messages": messages, "temperature": 0.8,
                                      "max_tokens": 64, "reasoning_effort": "off",
                                      "tool_choice": "none"}, headers)
    dt = time.time() - t0
    u = r.get("usage", {})
    det = u.get("prompt_tokens_details") or {}
    ch = r["choices"][0]
    ans = (ch["message"].get("content") or "").strip().replace("\n", " ")
    return ans, int(u.get("prompt_tokens") or 0), int(det.get("cached_tokens") or 0), dt, ch.get("finish_reason")

NUMTOK = re.compile(r"(?<![a-z0-9.])\d+(?:\.\d+)?(?!\d)(?!\.\d)")   # numbers, not "11" inside
#   "C11", and - the G3 period-fix family, fixed at the shared root between experiments
#   (2026-10-26): "0.06." at end of sentence or bold ("**0.06.**") now MATCHES - a gold
#   quoted with its sentence period was scored a miss (grad c6 x2; raw A 0.867 vs re-scored).
#   Old lookahead (?![\d.]) rejected any trailing dot; (?!\d)(?!\.\d) keeps the decimal-
#   split guard (never "0" from "0.065") while allowing prose punctuation.

def first_hit(vs, a):
    # Run-prep amendments (logged in Results, the C4 comma-variant precedent): digit boundaries
    # AND numeric equivalence - "1.00" is the gold 1.000, "18" is not the gold 8; version-like
    # markers (0.2.5) keep boundary-substring because they are not floats.
    best = None
    for v in vs:
        start = None
        if v.startswith("\\b"):
            m = re.search(v, a)
            start = m.start() if m else None
        elif re.fullmatch(r"[\d.]+", v):
            try:
                val = float(v)
            except ValueError:
                val = None                                     # 0.2.5 / 0.1.50: boundary-substring
            if val is not None:
                for m in NUMTOK.finditer(a):
                    if abs(float(m.group()) - val) < 1e-9 and (start is None or m.start() < start):
                        start = m.start()
            else:
                m = re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.])", a)
                start = m.start() if m else None
        else:
            m = re.search(re.escape(v), a)
            start = m.start() if m else None
        if start is not None and (best is None or start < best):
            best = start
    return best

def classify(ans, gid):
    # The smoke's scar, made law: a refusal that OPENS the answer abstains even when the answer
    # later names a marker ("I don't know - zero?" is not a recall); a marker that arrives
    # before any refusal phrase counts. Position decides. Digit-boundary matching per the
    # sweep's scar ("no" inside "knowledge" died here too).
    a = norm(ans)
    vs = dict((g, v) for g, _, _, v in GOLDS)[gid]
    gm = first_hit(vs, a)
    im = IDK.search(a)
    if gm is not None and not (im and im.start() <= gm):
        return "gold"
    if im:
        return "idk"
    loose = ("8", "1.0", "zero", "none", r"\b0\b", "not", "11")
    dm = first_hit([v for v in ALL_MARKERS if v not in loose], a)
    return "distractor" if dm is not None else "other"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    tag = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(BENCH, "g3_" + tag)
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, "g3_rows.jsonl")
    rows_f = open(rows_path, "w")
    HDR = [("X-Strata-Memory-Block", "off")]

    st = post("/memory?limit=1", None, [])["stats"]
    standing = (st.get("cartridges") or {}).get("file")
    assert standing, "no standing cart - G3 runs with the cartridge system on"
    carts_all = post("/memory", {"op": "carts"})["carts"]
    carts = {c["name"]: c for c in carts_all if c["name"] != "standing"}   # row zero IS the prefix
    order = sorted(carts)                                                  # ledger-name order
    bodies = {n: carts[n]["sources"]["text"] for n in order}
    LEAD = ("You are about to learn three short notes carried as carts. Learn them; "
            "acknowledge with OK only.\n\n"
            + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in order))
    print(f"G3 tag={tag} standing={standing} carts={order} "
          f"bodies={sum(len(b) for b in bodies.values()):,} chars", flush=True)

    def build_compose(fname, lead):
        slot("restore", standing)
        ack, pt, ca, dt, fr = chat([{"role": "user", "content": lead}], HDR)
        r = slot("save", fname)
        print(f"  compose {fname}: lead eval {pt - ca} tok, ack {ack[:24]!r}, "
              f"saved {r.get('n_saved')} rows / {int(r.get('n_written', 0)) / 1e6:.0f} MB", flush=True)
        return ack

    ack0 = build_compose(f"G3_COMPOSE_{tag}.bin", LEAD)
    lead2 = ("You are about to learn two short notes carried as carts. Learn them; "
             "acknowledge with OK only.\n\n"
             + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in order if n != "merge-notes"))
    build_compose(f"G3_C2_{tag}.bin", lead2)

    golds = GOLDS[:4] if a.smoke else GOLDS
    groups = [golds[i:i + 4] for i in range(0, len(golds), 4)]
    BLOCK = ("Reference notes (re-injected this turn):\n\n"
             + "\n\n".join(f"[{n}]\n{bodies[n]}" for n in order))
    STATE_LEAD = "Answer using only what you learned earlier. "
    n_pass = 1 if a.smoke else a.passes

    def row(arm, conv, p, gid, cart, q, cls, ans, pt, ca, dt, fr):
        rows_f.write(json.dumps({"tag": tag, "arm": arm, "conv": conv, "pass": p, "gold": gid,
                                 "cart": cart, "ask": q, "cls": cls, "ans": ans[:160],
                                 "ptok": pt, "eval": pt - ca, "s": round(dt, 2), "fr": fr}) + "\n")
        rows_f.flush()
        return cls

    def guard():
        f = post("/memory?limit=1", None, [])["stats"]["cartridges"]["file"]
        if f != standing:
            raise SystemExit(f"G3 ABORT: the standing cart rotated mid-run ({standing} -> {f})")

    results = {}
    for p in range(1, n_pass + 1):
        # ---- arm A: composed, bodies ride as cached text ----
        for ci, g in enumerate(groups):
            guard()
            slot("restore", f"G3_COMPOSE_{tag}.bin")
            conv = [{"role": "user", "content": LEAD}, {"role": "assistant", "content": ack0}]
            for gid, cart, q, _ in g:
                ans, pt, ca, dt, fr = chat(conv + [{"role": "user", "content": q}], HDR)
                results.setdefault(("A", cart), []).append(row("A", ci, p, gid, cart, q, classify(ans, gid), ans, pt, ca, dt, fr))
                conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        # ---- arm B: bodies injected after the conversation, re-evaluated ----
        for ci, g in enumerate(groups):
            guard()
            slot("restore", standing)
            conv = []
            for gid, cart, q, _ in g:
                ans, pt, ca, dt, fr = chat(conv + [{"role": "user", "content": BLOCK},
                                               {"role": "user", "content": q}], HDR)
                results.setdefault(("B", cart), []).append(row("B", ci, p, gid, cart, q, classify(ans, gid), ans, pt, ca, dt, fr))
                conv += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        # ---- arm C: state-only, bodies never re-sent ----
        for ci, g in enumerate(groups):
            for gid, cart, q, _ in g:
                guard()
                slot("restore", f"G3_COMPOSE_{tag}.bin")
                ans, pt, ca, dt, fr = chat([{"role": "user", "content": STATE_LEAD + q}], HDR)
                results.setdefault(("C", cart), []).append(row("C", ci, p, gid, cart, q, classify(ans, gid), ans, pt, ca, dt, fr))
        print(f"pass {p}/{n_pass} done", flush=True)

    # ---- the foreign control: merge-notes' gold asked WITHOUT its cart ----
    ctrl = []
    for p in range(1, n_pass + 1):
        slot("restore", f"G3_C2_{tag}.bin")
        q = dict((g, (c, qq)) for g, c, qq, _ in GOLDS)["m3"][1]
        ans, pt, ca, dt, fr = chat([{"role": "user", "content": STATE_LEAD + q}], HDR)
        cls = classify(ans, "m3")
        ctrl.append(cls)
        row("CTRL", -1, p, "m3", "merge-notes", q, cls, ans, pt, ca, dt, fr)

    rows_f.close()

    # ---- verdict ----
    def rate(arm, cart=None):
        vals = results[(arm, cart)] if cart else [v for c in carts for v in results[(arm, c)]]
        return sum(1 for v in vals if v == "gold") / max(len(vals), 1), len(vals)

    def med(arm):
        ev = sorted(json.loads(l)["eval"] for l in open(rows_path) if json.loads(l)["arm"] == arm)
        return ev[len(ev) // 2] if ev else 0

    lines = [f"G3 verdict @{datetime.datetime.now().isoformat(timespec='seconds')} tag={tag} "
             f"passes={n_pass} temp=0.8 block=off standing={standing}"]
    for arm in "ABC":
        r_all, n_all = rate(arm)
        per = {c: rate(arm, c)[0] for c in carts}
        lines.append(f"  arm {arm}: recall {r_all:.3f} (n={n_all}) per-cart "
                     + " ".join(f"{c.split('-')[0]}={per[c]:.3f}" for c in sorted(per))
                     + f" | median eval {med(arm)} tok")
    ra, _ = rate("A"); rb, _ = rate("B")
    lines.append(f"  GATE: A/B = {(ra / rb if rb else 0):.3f} (need >= 0.900 overall; per-cart in the rows)")
    lines.append(f"  PREFILL: median eval A={med('A')} B={med('B')} tok/ask")
    lines.append(f"  CONTROL (merge-notes asked without its cart): {ctrl} (gold once = leak note)")
    for arm in "ABC":
        buckets = {}
        for c in carts:
            for v in results[(arm, c)]:
                buckets[v] = buckets.get(v, 0) + 1
        lines.append(f"  buckets {arm}: {buckets}")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out_dir, f"g3_verdict_{tag}.txt"), "w") as f:
        f.write(txt + "\n")

if __name__ == "__main__":
    main()
