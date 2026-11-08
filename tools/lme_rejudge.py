#!/usr/bin/env python3
"""Re-score a LongMemEval venue run with a DIFFERENT judge - by default Grok via api.x.ai.

Why this exists: the venue harness judges with the box's own served model (tools/lme_harness.py::judge
- same weights as the model that wrote the answer, memory muted, temp 0, 10 tokens). That is a
self-answering instrument: the judge's quirks are correlated with the answerer's. The LongMemEval
paper judges with GPT-4o and meta-evaluates the prompt against human experts at >=90% agreement,
weakest on single-session-preference and abstention (paper Table 6, arXiv 2410.10813). An external
judge breaks the correlation, and it is the number a reader can compare with the paper's tables.

The cheap way to buy that: the answers are already paid for. A venue .jsonl carries the hypothesis,
the gold answer, the question id and the old verdict, so a judge swap costs judge calls only - no
ingest, no engine. This script re-runs the OFFICIAL checker prompt (imported from the harness, so
the prompt cannot drift between the two instruments) over an existing run and reports:

  ACCURACY    the new number, overall and per type, with the harness's own majority rule
  AGREEMENT   how the new judge voted against the one on file (counts + Cohen's kappa), per type
  SPEND       the tokens the API billed, priced at the rates on the box's copy of the docs

The questions come from the frozen data file, not the .jsonl, because the abstention template needs
the paper's `answer` (the explanation) and only the dataset carries it.

    .venv/bin/python tools/lme_rejudge.py \
        --in ~/Strata-data/bench/venue_accuracy_full_2026-10-23.jsonl \
        --model grok-4.7 --key-env XAI_API_KEY [--limit 100] [--workers 6]
    # the local arm, for an A/B against the instrument on file:
    ... --base-url http://127.0.0.1:8005 --model '' --key-env ''

Notes that bite:
- max_tokens 512, not the harness's 10: a reasoning judge spends its budget thinking before it says
  yes, and a 10-token cap scores it as a no. The parse is the LAST yes/no in the text (a chain of
  thought can say "yes" mid-sentence about the question), where the official eval's rule is
  "yes" in out on a 10-token reply. Both parses are recorded so the difference is auditable.
- a failed call counts incorrect, as in the harness; the line says why.
- prompts are ~250-700 tokens, far under xAI's 200k long-context threshold, so the standard rate
  applies to every call.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import statistics
import sys
import time
import urllib.request as U
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lme_harness import anscheck_prompt  # noqa: E402  the ONE checker prompt, shared by both arms

YES_NO = re.compile(r"\b(yes|no)\b", re.I)
# USD per million tokens, xAI docs 2026-11-08 (grok-4.7: $2 in / $6 out; the non-reasoning
# grok-4.20-0309 variant is $1.25 / $2.50). Override with --in-per-m / --out-per-m.
RATE = {"grok-4.7": (2.0, 6.0), "grok-4.6": (2.0, 6.0), "grok-4.3": (1.25, 2.50),
        "grok-4.20-0309-non-reasoning": (1.25, 2.50), "grok-4.20-0309-reasoning": (1.25, 2.50)}


def verdict(text: str) -> tuple[bool, bool]:
    """(last-token verdict, official "yes" in text verdict) from a judge reply."""
    hits = YES_NO.findall(text or "")
    return ((hits[-1].lower() == "yes") if hits else False, "yes" in (text or "").lower())


def call(base: str, model: str, key: str, prompt: str, max_tokens: int,
         temperature: float, timeout: float, tries: int = 3) -> dict:
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": temperature,
            "max_tokens": max_tokens}
    if model:
        body["model"] = model
    hdrs = {"Content-Type": "application/json"}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    last = "no attempts made"
    for i in range(tries):
        try:
            req = U.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                            method="POST", headers=hdrs)
            with U.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode())
            return {"ok": True,
                    "text": (j["choices"][0]["message"].get("content") or "").strip(),
                    "usage": j.get("usage") or {}}
        except Exception as e:                                       # noqa: BLE001 - a failed judge says no
            last = f"{type(e).__name__}: {e}"
            time.sleep(2.0 * (i + 1))                                # rate limits come back in seconds
    return {"ok": False, "text": "", "usage": {}, "err": last}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="a venue .jsonl from lme_harness")
    ap.add_argument("--data", default=str(Path.home() / "Strata-data/bench/longmemeval_oracle.json"))
    ap.add_argument("--base-url", default="https://api.x.ai/v1")
    ap.add_argument("--model", default="grok-4.7", help="'' for a server that infers the model (Strata)")
    ap.add_argument("--key-env", default="XAI_API_KEY", help="env var holding the bearer token; '' for none")
    ap.add_argument("--field", default="hypothesis", choices=["hypothesis", "cold_hypothesis"],
                    help="which answer text to judge (the muted control arm is the cold baseline)")
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N lines (pilot)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--in-per-m", type=float, default=-1.0, help="USD/M input; -1 = look up the model")
    ap.add_argument("--out-per-m", type=float, default=-1.0, help="USD/M output; -1 = look up the model")
    ap.add_argument("--out", default="", help="output .jsonl (default: <in>.<model>.rejudge.jsonl)")
    a = ap.parse_args()

    key = os.environ.get(a.key_env, "") if a.key_env else ""
    if a.base_url.startswith("https") and not key:
        print(f"[rejudge] {a.key_env} is unset - nothing to spend", file=sys.stderr)
        return 2

    qs = {q["question_id"]: q for q in json.load(open(a.data))}
    rows = [json.loads(l) for l in open(a.src) if l.strip()]
    if a.limit:
        rows = rows[:a.limit]
    # One judge call per (question, repeat) line. Lines that share a question are independent
    # answers, so the majority rule below has the same shape as the harness's.
    todo = [r for r in rows if r["question_id"] in qs]
    missing = len(rows) - len(todo)

    dest = Path(a.out) if a.out else Path(a.src).with_suffix("") 
    dest = Path(str(dest) + (f".{a.model or 'local'}" if a.model else ".local") + ".rejudge.jsonl")
    done = {}
    if dest.exists():                                    # resumable, like the harness's own --out
        for l in open(dest):
            o = json.loads(l)
            done[(o["question_id"], o["repeat"], o["field"])] = o
    queue = [r for r in todo if (r["question_id"], r["repeat"], a.field) not in done]
    print(f"[rejudge] {len(rows)} lines, {len(queue)} to judge, {len(done)} on file"
          + (f", {missing} with no dataset row" if missing else ""), flush=True)
    if not queue:
        rows = [done[(r["question_id"], r["repeat"], a.field)] for r in todo
                if (r["question_id"], r["repeat"], a.field) in done]

    def work(row):
        q = qs[row["question_id"]]
        prompt = anscheck_prompt(q["question_type"], q["question"], q["answer"],
                                 row.get(a.field) or "(empty)", q["question_id"].endswith("_abs"))
        t0 = time.time()
        r = call(a.base_url, a.model, key, prompt, a.max_tokens, a.temperature, a.timeout)
        last, official = verdict(r["text"])
        out = dict(row)
        out.update({"field": a.field, "judge_model": a.model or "served",
                    "rejudge_ok": r["ok"], "rejudge_verdict": last if r["ok"] else False,
                    "official_parse": official, "rejudge_sec": round(time.time() - t0, 1),
                    "usage": r.get("usage") or {}, "rejudge_err": r.get("err", "")})
        return out

    t0 = time.time()
    with dest.open("a") as fh, cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        n = 0
        for o in ex.map(work, queue):
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
            fh.flush()
            done[(o["question_id"], o["repeat"], a.field)] = o
            n += 1
            if n % 50 == 0:
                print(f"[rejudge] {n}/{len(queue)}  {time.time() - t0:.0f}s", flush=True)

    # ---- score: the harness's majority rule, on the new verdict and the old one side by side ----
    def majority(key_fn) -> tuple[dict, dict]:
        acc, per = defaultdict(list), defaultdict(list)
        by_q = defaultdict(list)
        for r in todo:
            o = done.get((r["question_id"], r["repeat"], a.field))
            if o is None:
                continue
            by_q[r["question_id"]].append((r["type"], bool(key_fn(o))))
        for qid, votes in by_q.items():
            ok = sum(v for _, v in votes) * 2 > len(votes)
            acc[votes[0][0]] = ok
            per[votes[0][0]].append(ok)
        overall = {t: round(sum(v) / len(v), 3) for t, v in sorted(per.items())}
        allv = [v for votes in per.values() for v in votes]
        return {"questions": len(allv), "accuracy": round(sum(allv) / max(1, len(allv)), 3)}, overall

    new, new_by = majority(lambda o: o["rejudge_verdict"])
    old, old_by = majority(lambda o: o.get("correct"))
    # agreement at the LINE level (the paper's unit of comparison is one judgment, not one majority)
    n = agree = 0
    tab = {"TP": 0, "TN": 0, "new_yes_old_no": 0, "new_no_old_yes": 0}
    per_type = defaultdict(lambda: [0, 0])
    for r in todo:
        o = done.get((r["question_id"], r["repeat"], a.field))
        if o is None:
            continue
        n += 1
        a_new, a_old = bool(o["rejudge_verdict"]), bool(o.get("correct"))
        agree += a_new == a_old
        tab["TP" if (a_new and a_old) else
            "new_yes_old_no" if a_new else
            "new_no_old_yes" if a_old else "TN"] += 1
        per_type[r["type"]][0] += 1
        per_type[r["type"]][1] += a_new == a_old
    p_yes = (tab["TP"] + tab["new_yes_old_no"]) / max(1, n)
    p_old = (tab["TP"] + tab["new_no_old_yes"]) / max(1, n)
    pe = p_yes * p_old
    kappa = (agree / max(1, n) - pe) / (1 - pe) if pe < 1 else 0.0

    pin = sum((o.get("usage") or {}).get("prompt_tokens", 0) for o in done.values())
    pout = sum((o.get("usage") or {}).get("completion_tokens", 0) for o in done.values())
    rin, rout = RATE.get(a.model, (0.0, 0.0))
    rin = a.in_per_m if a.in_per_m >= 0 else rin
    rout = a.out_per_m if a.out_per_m >= 0 else rout
    secs = [o.get("rejudge_sec", 0.0) for o in done.values() if o.get("rejudge_ok")]
    fails = sum(1 for o in done.values() if not o.get("rejudge_ok"))

    rep = {
        "in": str(a.src), "data": str(a.data), "field": a.field,
        "judge": f"{a.model or 'served model'} at {a.base_url} (official LongMemEval checker "
                 f"prompt, temp {a.temperature}, max_tokens {a.max_tokens}, last-token parse)",
        "instrument_on_file": rows[0].get("judge", ""),
        "lines": n, "failed_calls": fails,
        "new": {"overall": new, "by_type": new_by},
        "old": {"overall": old, "by_type": old_by},
        "agreement": {"rate": round(agree / max(1, n), 3), "kappa": round(kappa, 3),
                      "confusion": tab,
                      "by_type": {t: round(c / max(1, m), 3) for t, (m, c) in per_type.items()}},
        "latency_sec": {"median": round(statistics.median(secs), 1) if secs else None,
                        "p95": round(sorted(secs)[int(len(secs) * .95) - 1], 1) if len(secs) > 3 else None},
        "tokens": {"in": pin, "out": pout, "usd": round(pin / 1e6 * rin + pout / 1e6 * rout, 2)},
    }
    Path(str(dest) + ".metrics.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
