"""tools/livebox_browse_pilot.py - the pilot-20 question set, run on the LIVE store and the
LIVE persona box, both arms, one boot (2026-10-24 night).

This is NOT the Browse Day venue rerun - that day is banked (0.682, hybrid law, BROWSE_PRE_REG
Results). This closes the open queue item: does the browse arm FIRE on the daily box at all?
The venue ran the bare template; the daily box answers under the persona template (the standing
cart, skill.md teaching the store's verbs), and its tool ledger has read calls: 0 under real
traffic. Two explanations are on trial here - model-behavior (the persona declines to browse)
vs harness/prompt (the mechanism never fires) - and the pilot separates them by running the
browsed arm HERE: if the persona model drives the tool when the block is declined, the ledger's
silence is a prompt-pressure question, not a capability gap.

Instrument discipline: ask() and judge() are IMPORTED from lme_harness.py, not restated - the
same headers, the same ANSWER_RULES, the same official checker templates and temp-0 decoding,
the same muted judge. Fresh conversation per ask, temp 0.8, one repeat per question per arm
(pilot size, not a venue day). CAVEAT printed in the metrics: the store's embedder changed the
same night (embeddinggemma-2 era), so comparisons to the banked bge-era numbers (0.666 control,
0.682 browse day) are CROSS-INSTRUMENT; the served-vs-browsed comparison WITHIN this run is the
valid one.

    python tools/livebox_browse_pilot.py [--fixture PATH] [--url URL] [--arms served,browsed]

Records land in the bench dir (never /tmp): livebox_pilot_<date>.jsonl + .metrics.json.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lme_harness import ask, judge     # the frozen machinery, imported not restated

ROOT = Path(__file__).resolve().parent.parent
BENCH = Path.home() / "Strata-data" / "bench"


def tool_counters(url: str):
    import urllib.request
    req = urllib.request.Request(url + "/memory", headers={"Accept": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return (d["stats"].get("tool", {}), d["stats"]["embedder"].get("model", "?"),
            d["stats"]["memories"])


def main() -> int:
    ap = argparse.ArgumentParser(prog="livebox_browse_pilot")
    ap.add_argument("--fixture", default=str(ROOT / "spikes/lme/LIVEBOX_PILOT_2026-10-24.jsonl"))
    ap.add_argument("--url", default="http://127.0.0.1:8005")
    ap.add_argument("--scope", default="default")
    ap.add_argument("--arms", default="served,browsed")
    ap.add_argument("--out", default=str(BENCH / f"livebox_pilot_{datetime.date.today()}.jsonl"))
    a = ap.parse_args()

    qs = [json.loads(ln) for ln in Path(a.fixture).read_text(encoding="utf-8").splitlines() if ln.strip()]
    url = a.url.rstrip("/")
    out_path, recs = Path(a.out), []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for arm in [x.strip() for x in a.arms.split(",") if x.strip()]:
            browse = arm == "browsed"
            before, model, nrows = tool_counters(url)
            t_arm = time.time()
            for q in qs:
                r = ask(url, q, a.scope, muted=False, browse=browse)
                ok = judge(url, q, r["text"])
                rec = {"arm": arm, **{k: q[k] for k in
                       ("question_id", "question_type", "question", "answer", "row_ids")},
                       "response": r["text"], "sec": r["sec"], "rounds": r["rounds"],
                       "correct": ok, "embedder_model": model}
                recs.append(rec)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{arm:7}] {q['question_id']:18} {'yes' if ok else 'NO ':3} "
                      f"rounds {r['rounds']} {r['sec']:5.1f}s | {r['text'][:64]}")
            after, _, _ = tool_counters(url)
            delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
            acc = [r for r in recs if r["arm"] == arm]
            metrics = {
                "arm": arm, "n": len(acc), "overall": round(sum(r["correct"] for r in acc) / len(acc), 3),
                "by_type": {t: round(sum(r["correct"] for r in acc if r["question_type"] == t)
                                     / max(1, sum(r["question_type"] == t for r in acc)), 3)
                            for t in sorted({r["question_type"] for r in acc})},
                "tool_delta": delta, "mean_rounds": round(sum(r["rounds"] for r in acc) / len(acc), 2),
                "sec_median": sorted(r["sec"] for r in acc)[len(acc) // 2],
                "sec_p95": sorted(r["sec"] for r in acc)[int(len(acc) * 0.95) - 1],
                "wall_s": round(time.time() - t_arm, 1), "embedder_model": model, "store_rows": nrows,
                "caveat": "embedder swapped (embeddinggemma-2) the same night: cross-arm "
                          "comparison valid; vs banked bge-era 0.666/0.682 cross-instrument"}
            print(json.dumps(metrics, indent=1))
            with open(str(out_path).replace(".jsonl", ".metrics.json"), "a", encoding="utf-8") as mh:
                mh.write(json.dumps(metrics) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
