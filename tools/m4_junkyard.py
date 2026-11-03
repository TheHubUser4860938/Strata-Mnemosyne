#!/usr/bin/env python3
"""m4_junkyard - the store's two clean-ups in one pass: duplicates, and junk.

The owner's ruling, 2026-11-02: "manually sort and dedupe my entire memory store -
straight up delete anything that is a duplicate and junk." Sorting went first
(m4_reshelve + m4_shelftidy, 583 wild -> 63, 243 shelves -> 107). This is the other
two edges, on the FACT rows (the doc shelf is a corpus, not a memory):

  DUPLICATES   cosine over the vectors the store already carries, greedy clusters at
               `--bar` (0.85, the 2026-10-16 consolidation's own bar: it retired 421
               near-dup clusters and took the store 2,899 -> 2,478). The keeper is the
               row with the most to say - length first, then id, so the tie-break is
               deterministic and the same run always keeps the same row.

  JUNK         one clerk call per `--batch` rows: KEEP or JUNK, with a two-word reason.
               The clerk's own bar is stated in the prompt: a fact that will be true
               next week is KEEP; a status line, a counter, a garbled extraction, a
               decision about a file that no longer exists, is JUNK.

DELETE, not invalidate: `forget` retires a row and keeps it for history; the owner
asked for the pile gone. The review log is the history - every purged row is written
there with its text, its shelf, and why it went, so a deleted fact can be re-minted
from the log (the cart law: the record is text, the state is derived).

  python3 tools/m4_junkyard.py [--bar 0.85] [--dups] [--junk] [--apply]
                               [--class X] [--limit N] [--batch 8] [--keep K]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "serve")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                              # noqa: E402
from strata_control.datafolder import data_dir                  # noqa: E402
from serve.memory import MemoryService                          # noqa: E402

JUNK_PROMPT = """A memory store keeps facts about one person's projects, machine and life.
Decide which of these are worth KEEPING next month, and which are JUNK - a status line,
a run counter, a garbled extraction, a fact about a file that no longer exists, a restatement
of a fact already on the list.

Rules: one line per numbered item, `JUNK: <two words why>` or `KEEP`, nothing else.
A fact that will still be true and useful next month is KEEP.

{facts}
"""
# The clerk's verdict line, read as a DECISION: it writes "4. JUNK: run status" with a
# period after the number (the shape a numbered list takes), and the first junkyard run
# read that as zero verdicts - "0 of 2,249 junk" was a parser, not a clean store.
VERDICT = re.compile(r"^\s*(\d+)\s*[.:=)\]]*\s*(JUNK|KEEP)\b[:\- ]*(.*)$", re.M)
FILE_SECTION = re.compile(r"FILE\s*:", re.M | re.I)


def ask_box(prompt, url, max_tokens=700, timeout=180.0):
    body = json.dumps({"model": "strata", "temperature": 0.0, "max_tokens": max_tokens,
                       "messages": [{"role": "user",
                                     "content": "{REASON:off}\n\n" + prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310
        data = json.loads(resp.read().decode())
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    return str(msg.get("content") or msg.get("reasoning_content") or "")


def facts(svc, which: str, limit: int):
    q = ("select m.id, coalesce(m.class,''), m.text, m.updated_at from memories m"
         " where m.invalid_at is null and coalesce(m.scope,'') not like 'doc-%%'")
    params: list = []
    if which.upper() != "ALL":
        q += " and (m.class = %s or m.class like %s)"
        params += [which.upper(), which.upper() + "/%"]
    q += " order by m.id"
    if limit:
        q += " limit %s"
        params.append(limit)
    with svc.lock:
        rows = svc.conn.execute(q, params).fetchall()
        svc.conn.commit()
    return [(int(r[0]), r[1] or "", r[2], str(r[3])) for r in rows]


def vecs(svc, ids):
    with svc.lock:
        got = {r[0]: np.frombuffer(r[1], dtype=np.float32) for r in svc.conn.execute(
            "select id, vec from embeddings where id = any(%s)", (list(ids),)).fetchall()}
        svc.conn.commit()
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(data_dir(ROOT) / "memory-eval"))
    ap.add_argument("--bar", type=float, default=0.85, help="cosine that makes a duplicate")
    ap.add_argument("--dups", action="store_true")
    ap.add_argument("--junk", action="store_true")
    ap.add_argument("--class", dest="klass", default="ALL")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--url", default="http://127.0.0.1:8005/v1/chat/completions")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not (a.dups or a.junk):
        a.dups = a.junk = True

    svc = MemoryService(a.dir)
    rows = facts(svc, a.klass, a.limit)
    by_id = {r[0]: r for r in rows}
    out = Path(a.out or str(data_dir(ROOT) / "bench" /
                            f"m4-junkyard-{time.strftime('%Y-%m-%d')}.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"queue {len(rows)} fact rows; bar {a.bar}; dups={'on' if a.dups else 'off'}; "
          f"junk={'on' if a.junk else 'off'}; {'APPLY' if a.apply else 'dry run'}; log {out}")
    doomed: dict[int, str] = {}

    def purge(mid, why):
        doomed[mid] = why
        if a.apply:
            with svc.lock:
                svc.conn.execute("delete from embeddings where id=%s", (mid,))
                svc.conn.execute("delete from memories where id=%s", (mid,))
                svc.conn.commit()
                svc._vdirty = True
                svc._touched(reason="junkyard")

    with out.open("a", encoding="utf-8") as log:
        if a.dups:
            V = vecs(svc, [r[0] for r in rows])
            ids = [r[0] for r in rows if r[0] in V]
            if ids:
                M = np.stack([V[i] / max(np.linalg.norm(V[i]), 1e-9) for i in ids])
                S = M @ M.T
                seen: set[int] = set()
                n = 0
                for i, mid in enumerate(ids):
                    if mid in seen:
                        continue
                    grp = [ids[j] for j in range(i, len(ids)) if S[i][j] >= a.bar]
                    seen.update(grp)
                    keep = max(grp, key=lambda k: (len(by_id[k][2]), k))
                    for k in grp:
                        if k != keep:
                            n += 1
                            log.write(json.dumps({"id": k, "kind": "dup", "keep": keep,
                                                  "class": by_id[k][1],
                                                  "text": by_id[k][2][:200]}) + "\n")
                            purge(k, f"dup of {keep}")
                log.flush()
                print(f"dups: {n} rows clustered under a keeper at cosine >= {a.bar}")
        if a.junk:
            got = 0
            for i in range(0, len(rows), a.batch):
                chunk = [r for r in rows[i:i + a.batch] if r[0] not in doomed]
                if not chunk:
                    continue
                facts_txt = "\n".join(f"{j + 1}. {t[:240]}" for j, (_id, _c, t, _u) in enumerate(chunk))
                ans = ask_box(JUNK_PROMPT.format(facts=facts_txt), a.url, max_tokens=900)
                src = ans[FILE_SECTION.search(ans).end():] if FILE_SECTION.search(ans) else ans
                verd = {int(m.group(1)): (m.group(2), m.group(3).strip(" :"))
                        for m in VERDICT.finditer(src)}
                for j, (mid, klass, text, _u) in enumerate(chunk):
                    v = verd.get(j + 1)
                    if v and v[0] == "JUNK":
                        got += 1
                        log.write(json.dumps({"id": mid, "kind": "junk", "why": v[1],
                                              "class": klass, "text": text[:200]}) + "\n")
                        purge(mid, f"junk: {v[1]}")
                log.flush()
                print(f"  junk {min(i + a.batch, len(rows))}/{len(rows)} "
                      f"({got} marked)", flush=True)
            print(f"junk: {got} rows marked")
    print(f"\npurged: {len(doomed)} of {len(rows)} rows"
          + ("" if a.apply else "  (dry run - nothing written)"))
    svc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
