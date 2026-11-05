#!/usr/bin/env python3
"""The protocol bet, measured: text actions vs native tool calls.

Why this is the one architecture question worth a bench: a small quantized model
that emits its own action blocks does not need a tool-calling API, and that
changes what a substrate has to offer. Settle it on numbers, not on taste.

Two arms, same 12 tasks, same model, same temperature (1.0 — the owner's bench
rule, 2026-10-25), three repeats:

  native     the OpenAI-style `tools` field; the model answers with tool_calls
  protocol   no `tools` field; the model answers with a ```evolv fenced JSON block
             (the shape EVOLV ships, internal/agent/protocol.go:41)

Both arms run the SAME mini executor (one verb: shell), and the score is the
final answer against a gold computed from a direct run of the same command.

Parsing lives in ONE place: the raw transcript is written to JSONL and scored by
`node bench/p1/protocol_score.mjs`, which imports build/lib/protocol.mjs. This
script does not reimplement the parser, so the arm and the harness cannot drift.

Run: .venv/bin/python bench/p1/protocol_ab.py --repeats 3
Out: bench/p1/protocol-ab-<date>.jsonl  + the printed table
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date

URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8005")
REPO = os.path.expanduser("~/Projects/Strata-Mnemosyne")

PROTOCOL_SYSTEM = (
    "You run shell commands to answer the question, then answer in one line.\n"
    "To run a command, reply with ONLY a fenced block in this format:\n\n"
    "```evolv\n"
    '{"action": "shell", "command": "the command"}\n'
    "```\n\n"
    "You may put several actions in one block, one JSON object per line. When you "
    "have the result, answer with the number or phrase alone, no prose."
)
NATIVE_SYSTEM = (
    "You run shell commands to answer the question, then answer in one line, "
    "the number or phrase alone, no prose."
)
TOOLS = [{
    "type": "function",
    "function": {
        "name": "shell",
        "description": "Run a shell command in the repo and return its stdout.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "the command"}},
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}]

# the frozen panel: (question, the command whose stdout is the gold)
PANEL = [
    ("How many lines are in serve/memory.py?", "wc -l < serve/memory.py"),
    ("How many lines are in tools/curate_loop.py?", "wc -l < tools/curate_loop.py"),
    ("How many Python files are under serve/?", "find serve -name '*.py' | wc -l"),
    ("How many commits are on this branch?", "git rev-list --count HEAD"),
    ("How many active rows does the shelf hold? Use the stats file, not the port.",
     "psql -h /home/eugene/Strata-data/memory-eval/.s.PGSQL.5433 -U eugene -d strata -At -c \"select count(*) from memories where invalid_at is null\" 2>/dev/null || echo psql-unavailable"),
    ("What is the first word of AGENTS.md?", "head -c 400 AGENTS.md | tr -s ' \\n' ' ' | cut -d' ' -f1"),
    ("How many .md files are in docs/?", "find docs -name '*.md' | wc -l"),
    ("How many lines is the longest file in tools/?", "wc -l tools/*.py | sort -n | tail -2 | head -1 | awk '{print $1}'"),
    ("How many test files are under serve/?", "ls serve/test_*.py | wc -l"),
    ("How big is the Q8 PLE table file, in whole MB?",
     "du -m /home/eugene/Strata-data/models/Qwen3.8-Flash-Next-GSQ-RCO-Q8_0-00002-of-00002.gguf | cut -f1"),
    ("How many git tags exist?", "git tag | wc -l"),
    ("How many steps does the Clio build list carry?",
     "python3 -c \"import json,os;print(len(json.load(open(os.path.expanduser('~/Projects/Clio/build/steps.json')))['steps']))\""),
]


def call(payload: dict, timeout: int = 300, attempts: int = 4):
    """One chat call. The box is busy with a live session, so a slow read is retried."""
    last = None
    for i in range(attempts):
        req = urllib.request.Request(URL + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode() or "{}")
            return body, round((time.time() - t0) * 1000)
        except Exception as e:                                    # noqa: BLE001
            # 3.14 raises bare TimeoutError from the socket read, and http.client
            # can surface RemoteDisconnected; a busy box answers both on the next try
            last = e
            if i + 1 < attempts:
                time.sleep(3 * (i + 1))
    raise last


def norm(s: str) -> str:
    return " ".join(str(s or "").lower().replace(",", "").split())


def run_shell(command: str) -> str:
    try:
        p = subprocess.run(command, shell=True, cwd=REPO, capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr or "").strip()
    except Exception as e:                                   # noqa: BLE001
        return f"error: {e}"


def first_action_native(msg: dict):
    calls = msg.get("tool_calls") or []
    if not calls:
        return None
    try:
        args = json.loads(calls[0].get("function", {}).get("arguments") or "{}")
    except json.JSONDecodeError:
        return {"action": "shell", "command": "", "broken": True}
    return {"action": "shell", "command": args.get("command", "")}


def extract_action_protocol(text: str, node: str) -> dict | None:
    """One action out of a ```evolv block, using the harness parser."""
    out = subprocess.run([node, os.path.expanduser("~/Projects/Clio/bench/protocol_pick.mjs")],
                         input=text, capture_output=True, text=True, timeout=60).stdout.strip()
    if not out:
        return None
    return json.loads(out)


def one(arm: str, question: str, cmd: str, model: str, node: str, temp: float) -> dict:
    gold = run_shell(cmd)
    if arm == "native":
        messages = [{"role": "system", "content": NATIVE_SYSTEM}, {"role": "user", "content": question}]
        payload = {"model": model, "messages": messages, "tools": TOOLS, "temperature": temp}
    else:
        messages = [{"role": "system", "content": PROTOCOL_SYSTEM}, {"role": "user", "content": question}]
        payload = {"model": model, "messages": messages, "temperature": temp}

    ptok = ctok = 0
    ms = 0
    actions = 0
    broken = 0
    final = ""
    for step in range(3):                                   # one command, one answer, one spare
        body, took = call(payload)
        ms += took
        u = body.get("usage") or {}
        ptok += u.get("prompt_tokens") or 0
        ctok += u.get("completion_tokens") or 0
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        payload["messages"] = messages
        if arm == "native":
            got = first_action_native(msg)
            if got is None:
                final = (msg.get("content") or "").strip()
                break
            actions += 1
            if got.get("broken"):
                broken += 1
            messages.append(msg)
            messages.append({"role": "tool", "tool_call_id": (msg.get("tool_calls") or [{}])[0].get("id", "c"),
                             "content": run_shell(got["command"])})
            payload["messages"] = messages
        else:
            text = (msg.get("content") or "").strip()
            got = extract_action_protocol(text, node)
            if got is None:
                final = text
                break
            actions += 1
            if got.get("broken"):
                broken += 1
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": run_shell(got.get("command", ""))})
            payload["messages"] = messages
    return {
        "arm": arm, "question": question, "gold": gold, "answer": final,
        # "3,859 lines" answers "3859": compare on the digits, not the punctuation
        "ok": bool(gold) and norm(gold.splitlines()[0]) in norm(final),
        "actions": actions, "broken": broken, "prompt_tokens": ptok,
        "completion_tokens": ctok, "ms": ms, "steps": len(messages),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--model", default="")
    ap.add_argument("--temp", type=float, default=1.0)
    ap.add_argument("--node", default=os.environ.get("NODE", "node"))
    ap.add_argument("--out", default=f"bench/p1/protocol-ab-{date.today().isoformat()}.jsonl")
    a = ap.parse_args()

    health = json.loads(urllib.request.urlopen(URL + "/health", timeout=20).read().decode())
    model = a.model or health.get("model") or "swift"
    print(f"model={model} temp={a.temp} repeats={a.repeats} tasks={len(PANEL)}", flush=True)

    rows = []
    with open(os.path.join(REPO, a.out), "w", encoding="utf-8") as fh:
        for rep in range(a.repeats):
            for question, cmd in PANEL:
                for arm in ("native", "protocol"):
                    r = one(arm, question, cmd, model, a.node, a.temp)
                    r["repeat"] = rep + 1
                    rows.append(r)
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
                    print(f"  rep{rep+1} {arm:9} ok={int(r['ok'])} acts={r['actions']} broken={r['broken']} "
                          f"ptok={r['prompt_tokens']} {r['ms']}ms :: {r['answer'][:44]}", flush=True)
    print(f"records -> {a.out}")
    print("score with: node ~/Projects/Clio/bench/protocol_score.mjs " + os.path.join(REPO, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
