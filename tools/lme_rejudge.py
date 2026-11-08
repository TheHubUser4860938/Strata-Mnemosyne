#!/usr/bin/env python3
"""Re-score a LongMemEval venue run with a DIFFERENT judge.

Why this exists: the venue harness judges with the box's own served model (tools/lme_harness.py::judge
- same weights as the model that wrote the answer, memory muted, temp 0, 10 tokens). That is a
self-answering instrument: the judge's quirks are correlated with the answerer's. The LongMemEval
paper judges with GPT-4o and meta-evaluates the prompt against human experts at >=90% agreement,
weakest on single-session-preference and abstention (paper Table 6, arXiv 2410.10813). An external
judge breaks the correlation.

The answers are already paid for. A venue .jsonl carries the hypothesis, the gold answer, the
question id and the old verdict, so a judge swap costs JUDGMENTS ONLY - no ingest, no engine.

Two instruments, one prompt (imported from the harness, so it cannot drift between them):

  API     .venv/bin/python tools/lme_rejudge.py --in venue.jsonl --model grok-4.7 --key-env XAI_API_KEY
          one call per line, parallel, resumable, priced.

  WEB     .venv/bin/python tools/lme_rejudge.py --in venue.jsonl --repeats 1 --emit-packet PKIT.md
          ...paste PKIT.md into grok.com (Expert mode, web search OFF), save the reply as REPLY.txt...
          .venv/bin/python tools/lme_rejudge.py --in venue.jsonl --parse-reply REPLY.txt
          No key, no bill. The packet's numbered items and its .items.json sidecar make the reply
          machine-readable, and both files are the record: the judge is a chat, so the transcript is
          the run log. Keep the same settings for every batch of one run - the instrument freezes.

The scoring is the harness's own majority rule (>= half the repeats judged correct), and the report
carries the AGREEMENT with the verdict on file (rate + Cohen's kappa, per type), because a judge swap
and a system change both move the number - the agreement table is what separates them.

Notes that bite:
- The official checker asks ONE item at a time ("Answer yes or no only"). The packet asks a numbered
  list to fit a chat, which is a disclosed deviation: the RULES text is verbatim per question type,
  the batching is not. The metrics line says "batched".
- Abstention questions use the paper's unanswerable template, and their "answer" is the explanation -
  only the dataset carries it, so the questions come from the frozen data file, never the .jsonl.
- A reasoning judge needs room to think: max_tokens 512, not the harness's 10, and the parse is the
  LAST yes/no in the text (a chain of thought can say "yes" mid-sentence). Both parses are recorded.
- A failed call counts incorrect, as in the harness; the line says why.
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
# The packet's one-line instruction per group: the paper's core rule, verbatim, above its items.
# The template is `core + tail`, and the tail begins with a blank line then "Question:" - so that
# is the seam. (The first version matched `^I will give you.*?Answer yes or no only\.`: that
# sentence sits at the END of every template, so the non-greedy match swallowed the whole prompt
# and each item kept only the bytes past the FIRST item's length - item 1 rendered empty, item 2
# rendered "it earlier than the time management workshop...", and Grok judged exactly that.)
RULE_SEAM = "\n\nQuestion: "


def verdict(text: str) -> tuple[bool, bool]:
    """(last-token verdict, official "yes" in text verdict) from a judge reply."""
    hits = YES_NO.findall(text or "")
    return ((hits[-1].lower() == "yes") if hits else False, "yes" in (text or "").lower())


def load(rows_path: str, data_path: str, field: str, limit: int, repeats: int,
         per_type: int = 0) -> tuple[dict, list]:
    """(question map, the items to judge) - the SAME order in packet mode and in API mode, so a
    reply's numbers mean exactly what the packet's numbers meant.

    The oracle file is GROUPED BY TYPE, so the first 30 lines are all temporal-reasoning and a paste
    of 30 reads one rule. `per_type` takes the first N of every type instead - 5 x 7 types covers the
    panel the paper says its own judge is weakest on (preference, abstention)."""
    qs = {q["question_id"]: q for q in json.load(open(data_path))}
    rows = [json.loads(l) for l in open(rows_path) if l.strip()]
    seen: dict[str, int] = defaultdict(int)
    type_n: dict[str, int] = defaultdict(int)
    items = []
    for r in rows:
        q = qs.get(r["question_id"])
        if q is None:
            continue
        if seen[r["question_id"]] >= repeats:
            continue
        if per_type and type_n[r["type"]] >= per_type:
            continue
        seen[r["question_id"]] += 1
        type_n[r["type"]] += 1
        items.append({"n": len(items) + 1, "question_id": r["question_id"], "repeat": r["repeat"],
                      "type": r["type"], "gold_row": r.get("correct"),
                      "prompt": anscheck_prompt(q["question_type"], q["question"], q["answer"],
                                                r.get(field) or "(empty)",
                                                q["question_id"].endswith("_abs"))})
        if limit and len(items) >= limit:
            break
    return qs, items


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
            return {"ok": True, "text": (j["choices"][0]["message"].get("content") or "").strip(),
                    "usage": j.get("usage") or {}}
        except Exception as e:                                       # noqa: BLE001 - a failed judge says no
            last = f"{type(e).__name__}: {e}"
            time.sleep(2.0 * (i + 1))                                # rate limits come back in seconds
    return {"ok": False, "text": "", "usage": {}, "err": last}


def emit_packet(items: list, path: Path) -> None:
    """A paste-ready batch, grouped by question type so each group carries ITS OWN official rules."""
    by: dict[str, list] = defaultdict(list)
    for it in items:
        by[it["type"]].append(it)
    out = ["Judge these memory answers. For each item, answer `yes` if the Model Response contains "
           "the Correct Answer under the rules of its group, else `no`. Reply with one line per "
           "item, numbered, and nothing else - `<number>. yes` or `<number>. no`.", ""]
    for t in sorted(by, key=lambda k: -len(by[k])):
        rule, _, _ = by[t][0]["prompt"].partition(RULE_SEAM)
        out += [f"## {t}  ({len(by[t])} items)", "", rule.strip(), ""]
        for it in by[t]:
            _, seam, body = it["prompt"].partition(RULE_SEAM)   # the tail only: Question/Answer/Response
            out += [f"{it['n']}. {seam.strip()} {body.strip().replace(chr(10), ' ')}", ""]
    path.write_text("\n".join(out), encoding="utf-8")
    Path(str(path) + ".items.json").write_text(
        json.dumps([{k: it[k] for k in ("n", "question_id", "repeat", "type", "gold_row")}
                    for it in items], indent=1))


def parse_reply(path: Path, n_items: int = 0) -> dict[int, bool]:
    """{item number: verdict} from a saved chat reply. Last yes/no on the line wins, so
    "3. yes, because the answer names the webinar" reads as yes and a self-correcting line
    ("7. no - yes") reads as the correction.

    Two shapes a judge really produces: numbered lines (what the packet asks for) and a BARE list
    of yes/no in item order - Grok answered that way on 2026-11-08. When no line carries a number,
    the list is read positionally, which is exactly why the packet numbers its items in one global
    sequence and the sidecar records them in the same order."""
    got: dict[int, bool] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:\*\*)?(\d{1,4})\s*(?:[.):]\s*)?(.+)$", line)
        if not m:
            continue
        v, _ = verdict(m.group(2))
        got[int(m.group(1))] = v
    if got or not n_items:
        return got
    # a bare list: every line that says yes or no, in order, read against the packet's own sequence
    seq = [verdict(l)[0] for l in lines if YES_NO.search(l)]
    if len(seq) < n_items:
        print(f"[rejudge] reply has {len(seq)} verdicts for {n_items} items - the short tail counts no",
              file=sys.stderr)
    return {i + 1: v for i, v in enumerate(seq[:n_items])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="a venue .jsonl from lme_harness")
    ap.add_argument("--data", default=str(Path.home() / "Strata-data/bench/longmemeval_oracle.json"))
    ap.add_argument("--field", default="hypothesis", choices=["hypothesis", "cold_hypothesis"],
                    help="which answer text to judge (the muted control arm is the cold baseline)")
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N lines")
    ap.add_argument("--repeats", type=int, default=3, help="repeats per question to judge")
    ap.add_argument("--per-type", type=int, default=0,
                    help="take the first N of EVERY type (the dataset is grouped; 5 covers all 7)")
    # ---- the API arm ----
    ap.add_argument("--base-url", default="https://api.x.ai/v1")
    ap.add_argument("--model", default="grok-4.7", help="'' for a server that infers the model (Strata)")
    ap.add_argument("--key-env", default="XAI_API_KEY", help="env var holding the bearer token; '' for none")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--in-per-m", type=float, default=-1.0, help="USD/M input; -1 = look up the model")
    ap.add_argument("--out-per-m", type=float, default=-1.0, help="USD/M output; -1 = look up the model")
    # ---- the web arm ----
    ap.add_argument("--emit-packet", default="", help="write a paste-ready batch here and stop")
    ap.add_argument("--parse-reply", default="", help="score a saved chat reply (reads <reply>.items.json)")
    ap.add_argument("--items", default="", help="the packet's .items.json, when the reply was saved elsewhere")
    ap.add_argument("--out", default="", help="output .jsonl (default: <in>.<judge>.rejudge.jsonl)")
    a = ap.parse_args()

    qs, items = load(a.src, a.data, a.field, a.limit, a.repeats, a.per_type)
    if not items:
        print("[rejudge] nothing to judge - check --in / --data / --limit", file=sys.stderr)
        return 2
    rows = [json.loads(l) for l in open(a.src) if l.strip()]

    if a.emit_packet:
        p = Path(a.emit_packet)
        emit_packet(items, p)
        print(f"[rejudge] packet: {len(items)} items ({len({i['question_id'] for i in items})} "
              f"questions, repeats<= {a.repeats}) -> {p}\n[paste {p} into the judge, save the reply, "
              f"then: --parse-reply <reply>]")
        return 0

    done: dict[tuple, dict] = {}
    dest = Path(a.out) if a.out else Path(str(Path(a.src).with_suffix("")) +
                                          (f".{a.model}" if a.model else ".local") + ".rejudge.jsonl")
    if a.parse_reply:
        # THE SIDECAR CONTRACT: the packet's .items.json sits at "<reply>.items.json" - save the
        # judge's reply under the packet's name plus a suffix and nothing has to be pointed at.
        # --items names it by hand when the reply lives somewhere else (a pasted .txt, a browser save).
        side = Path(a.items) if a.items else Path(a.parse_reply + ".items.json")
        if not side.exists():
            print(f"[rejudge] no sidecar at {side} - pass --items <packet.md.items.json>",
                  file=sys.stderr)
            return 2
        want = {it["n"]: it for it in json.loads(side.read_text())}
        got = parse_reply(Path(a.parse_reply), len(want))   # a bare yes/no list is read in order
        miss = sorted(set(want) - set(got))
        for n, ok in got.items():
            it = want.get(n)
            if it is None:
                continue
            src = next((r for r in rows if r["question_id"] == it["question_id"]
                        and r["repeat"] == it["repeat"]), None)
            if src is None:
                continue
            done[(it["question_id"], it["repeat"], a.field)] = {
                **src, "field": a.field, "judge_model": "grok-web", "rejudge_ok": True,
                "rejudge_verdict": ok, "official_parse": ok, "rejudge_sec": 0.0, "usage": {},
                "rejudge_err": ""}
        print(f"[rejudge] reply: {len(got)} lines read, {len(done)} verdicts matched"
              + (f", {len(miss)} items UNANSWERED (they count no)" if miss else ""))
        a.model = "grok-web"
        a.base_url = "chat"
    else:
        key = os.environ.get(a.key_env, "") if a.key_env else ""
        if a.base_url.startswith("https") and not key:
            print(f"[rejudge] {a.key_env} is unset - nothing to spend", file=sys.stderr)
            return 2
        if dest.exists():                                    # resumable, like the harness's own --out
            for l in open(dest):
                o = json.loads(l)
                done[(o["question_id"], o["repeat"], o["field"])] = o
        queue = [it for it in items if (it["question_id"], it["repeat"], a.field) not in done]
        print(f"[rejudge] {len(items)} items to judge, {len(done)} on file ({a.model}@{a.base_url})",
              flush=True)

        def work(it):
            t0 = time.time()
            r = call(a.base_url, a.model, key, it["prompt"], a.max_tokens, a.temperature, a.timeout)
            last, official = verdict(r["text"])
            src = next((x for x in rows if x["question_id"] == it["question_id"]
                        and x["repeat"] == it["repeat"]), {})
            return {**src, "field": a.field, "judge_model": a.model or "served", "rejudge_ok": r["ok"],
                    "rejudge_verdict": last if r["ok"] else False, "official_parse": official,
                    "rejudge_sec": round(time.time() - t0, 1), "usage": r.get("usage") or {},
                    "rejudge_err": r.get("err", "")}

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

    # ---- score: the harness's majority rule, the new verdict and the old one side by side ----
    def majority(key_fn) -> tuple[dict, dict]:
        per: dict[str, list] = defaultdict(list)
        by_q: dict[str, list] = defaultdict(list)
        for o in done.values():
            if o.get("field") != a.field:
                continue
            by_q[o["question_id"]].append((o["type"], bool(key_fn(o))))
        for qid, votes in by_q.items():
            per[votes[0][0]].append(sum(v for _, v in votes) * 2 > len(votes))
        allv = [v for votes in per.values() for v in votes]
        return ({"questions": len(allv), "accuracy": round(sum(allv) / max(1, len(allv)), 3)},
                {t: round(sum(v) / len(v), 3) for t, v in sorted(per.items())})

    new, new_by = majority(lambda o: o["rejudge_verdict"])
    old, old_by = majority(lambda o: o.get("correct"))
    n = agree = 0
    tab = {"TP": 0, "TN": 0, "new_yes_old_no": 0, "new_no_old_yes": 0}
    per_type = defaultdict(lambda: [0, 0])
    for o in done.values():
        if o.get("field") != a.field:
            continue
        n += 1
        a_new, a_old = bool(o["rejudge_verdict"]), bool(o.get("correct"))
        agree += a_new == a_old
        tab["TP" if (a_new and a_old) else "new_yes_old_no" if a_new else
            "new_no_old_yes" if a_old else "TN"] += 1
        per_type[o["type"]][0] += 1
        per_type[o["type"]][1] += a_new == a_old
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
        "judge": f"{a.model or 'served model'} at {a.base_url} (official LongMemEval checker rules, "
                 f"temp {a.temperature}, max_tokens {a.max_tokens}, last-token parse, "
                 f"{'BATCHED one-reply-per-group' if a.parse_reply else 'one prompt per item'})",
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
    dest.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in done.values()) + "\n")
    # the web arm's record IS the reply, so the merged verdicts are written too: a reader can check
    # any number against the line it came from without re-reading the chat.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
