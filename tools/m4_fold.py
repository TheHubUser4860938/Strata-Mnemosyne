#!/usr/bin/env python3
"""m4_fold.py — fold near-duplicate facts into one row, and keep the scar.

The clerk files a fact in a drawer; the law supersedes a restatement of the SAME claim.
Neither of them handles the shape the owner keeps hitting: a dozen rows that are each true,
each slightly different, and each useless alone —

    #1482  prefers sequential completion of work orders
    #1483  long-running tasks first
    #1484  efficiency during sleep periods
    #1485  the 2026-11-11 output format for the ordering task
    #1486  task 2 before task 1

A search for "work orders" returns five hits where one composite fact should do. Folding
groups rows by the store's OWN embeddings (no new index, no new model) and asks the served
model to write one fact that carries every distinct claim, dated where dated. The oldest row
in the group SURVIVES as the composite, so the chain reads forward through ids and the merged
rows keep pointing at it.

    python tools/m4_fold.py --dry-run --limit 5         # show the groups, write nothing
    python tools/m4_fold.py --shelf USR                 # fold one family
    python tools/m4_fold.py --min-cos 0.86 --limit 50

Cost: one LLM call per group, temp 0.8, 420 tokens out. The clustering is free.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from serve.memory import attach                                     # noqa: E402

MERGE_PROMPT = """Write ONE memory fact that carries every distinct claim below.
Rules: keep numbers, ids, dates and file paths exactly as written; drop duplicated claims;
no preamble, no bullets; 70 words maximum; state it as a fact, not as a request.

FACTS
%s

ONE FACT:"""


def ask(url, prompt, temperature=0.8, max_tokens=420):
    body = json.dumps({"model": os.environ.get("STRATA_MODEL", "strata"),
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": temperature, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url.rstrip("/") + "/memory", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def get(url, qs):
    with urllib.request.urlopen(url.rstrip("/") + "/memory?" + qs, timeout=120) as r:
        return json.load(r)


def unpack(blob):
    """`embeddings.vec` is packed little-endian float32 — 3,072 of them."""
    if not blob:
        return []
    import struct
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob[: n * 4]))


def norm(v):
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v] if n else v


def cluster(rows, min_cos):
    """Greedy transitive grouping on the store's own vectors. O(n²) at fact scale (~3k rows,
    ~4.5 M dot products of 3072-dim — seconds), and a row joins the first group it fits."""
    groups, used = [], set()
    for i, a in enumerate(rows):
        if i in used:
            continue
        grp = [i]
        used.add(i)
        for j in range(i + 1, len(rows)):
            if j in used:
                continue
            if rows[i]["scope"] != rows[j]["scope"]:
                continue          # scope, not class: one topic's rows sit on three shelves
            if rows[i]["cos"](rows[j]) >= min_cos:
                grp.append(j)
                used.add(j)
        if len(grp) > 1:
            groups.append(grp)
    return groups


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=os.environ.get("STRATA_STORE", "/home/eugene/Strata-data/memory-eval"))
    ap.add_argument("--url", default=os.environ.get("STRATA_URL", "http://127.0.0.1:8005"))
    ap.add_argument("--shelf", default="", help="fold one shelf family (prefix match), e.g. USR")
    ap.add_argument("--min-cos", type=float, default=0.82)
    ap.add_argument("--session-days", type=int, default=0,
                    help="retire lane=session facts older than N days (a session fact is true "
                         "for the conversation that wrote it: 'the user requested X', 'today we "
                         "are testing Y'), then return")
    ap.add_argument("--limit", type=int, default=20, help="max groups per run")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.session_days:
        # A session fact is true for the conversation that wrote it. "The user requested to
        # derive idempotency keys from task ids" describes a boot, not a rule, and a month
        # later it is noise that costs a slot in the recall block. Retire it; the chain keeps
        # the row visible under `superseded` so the scar survives.
        conn = attach(a.dir)
        # The lane rides in the jsonb `provenance` (`provenance->>'lane'`), written by the harvest — the same expression the
        # shelf census counts by, so the two agree.
        stale = conn.execute(
            "SELECT id, text, created_at FROM memories "
            "WHERE invalid_at IS NULL AND provenance->>'lane' = 'session' "
            "AND created_at < now() - (%s * interval '1 day') ORDER BY created_at",
            (a.session_days,)).fetchall()
        conn.close()
        print(f"session facts older than {a.session_days} days: {len(stale)}")
        for rid, text, created in stale[:max(1, a.limit)]:
            print(f"  #{rid} {str(created)[:10]} · {(text or '')[:90]}")
            if not a.dry_run:
                post(a.url, {"op": "invalidate", "id": rid})
        if not a.dry_run and len(stale) > a.limit:
            print(f"  … and {len(stale) - a.limit} more")
        return

    conn = attach(a.dir)
    # Vectors live in ONE table as packed float32 in a bytea (`embeddings(id, vec, model)`),
    # one model stamp per row — so the fold reads the stamp the store is serving and unpacks.
    stamp = conn.execute("SELECT model FROM embeddings GROUP BY model ORDER BY count(*) DESC LIMIT 1"
                         ).fetchone()[0]
    rows = conn.execute(
        "SELECT m.id, m.class, m.scope, m.text, m.hits, e.vec FROM memories m "
        "JOIN embeddings e ON e.id = m.id AND e.model = %s "
        "WHERE m.invalid_at IS NULL AND m.source NOT LIKE 'doc-index%%' ORDER BY m.id",
        (stamp,)).fetchall()
    conn.close()
    facts = [{"id": r[0], "class": r[1], "scope": r[2], "text": (r[3] or "").strip(),
              "hits": r[4] or 0, "v": norm(unpack(r[5]))} for r in rows]
    facts = [f for f in facts if f["v"]]
    if a.shelf:
        facts = [f for f in facts if (f["class"] or "").upper().startswith(a.shelf.upper())]
    for f in facts:
        f["cos"] = lambda o, v=f["v"]: sum(x * y for x, y in zip(v, o["v"]))

    groups = cluster(facts, a.min_cos)[:a.limit]
    if not groups:
        print("no groups at this threshold")
        return
    total = 0
    for grp in groups:
        members = [facts[i] for i in grp]   # cluster returns positions in `facts`
        members.sort(key=lambda f: f["id"])
        # Survive the most-used row when one is clearly the workhorse: a fact recalled 90 times
        # carries the shelf's reading of the topic, and folding it into a fresh row resets that.
        keep = max(members, key=lambda f: (f["hits"], -f["id"]))
        others = [f for f in members if f["id"] != keep["id"]]
        print(f"\ngroup {len(members)} · keep #{keep['id']} · fold {[f['id'] for f in others]}")
        for f in members:
            print(f"   #{f['id']} {f['text'][:100]}")
        if a.dry_run:
            continue
        prompt = MERGE_PROMPT % "\n".join(f"- {f['text']}" for f in members)
        merged = ask(a.url, prompt).strip()
        if not merged:
            print("   (empty answer, group left alone)")
            continue
        # op=correct writes a NEW row and points the old one at it, so the chain and the
        # provenance ride the mechanism the store already has. The merged row names its parts.
        res = post(a.url, {"op": "correct", "id": keep["id"], "text": merged,
                           "class": keep["class"], "scope": keep["scope"],
                           "provenance": {"folded": [f["id"] for f in others]},
                           "why": f"folded {len(members)} rows"})
        new_id = (res.get("result") or res).get("id")
        for f in others:
            post(a.url, {"op": "invalidate", "id": f["id"], "by": new_id})
        print(f"   → #{new_id} {merged[:120]}")
        total += len(others)
    print(f"\nfolded {total} rows into {len(groups) if not a.dry_run else 0} composites"
          + (" (dry run, nothing written)" if a.dry_run else ""))


if __name__ == "__main__":
    main()
