#!/usr/bin/env python3
"""m4_lme_purge.py — purge the LongMemEval test data from the memory store.

The LME ladder (2026-10/11) ingested the oracle corpus's synthetic persona chats as turns;
the harvest's clerk then EXTRACTED facts from them, so the test data rides the store as
ordinary fact rows ("Alex adopted a baby girl in January 2026", "Keeps a 30-gallon fish
tank"). The 2026-11-09 purge deleted the 2,660 `lme_*` ROWS and the 168 lme turns; the
extracted facts survived, and later ladder days added more. Three rules find what is left:

  1. DEAD-TURN — the fact's provenance names a `turn_id` that is no longer in the turns
     table: it was extracted from a purged ladder turn. The clean join, and the big one.
  2. VERBATIM — the fact shares >= 2 word 6-grams with the oracle corpus text (the clerk
     compresses, so this catches the quoted-verbatim tail, not the paraphrase mass).
  3. MARKED — the fact's provenance carries an lme / longmemeval mark of its own.

Plus --extra-ids: rows the owner names by hand. The purge union is flagged ∪ extra.
Purge is the hard-delete verb (MemoryService.purge): row and embedding go, and the
`purges` ledger keeps the sha256 + a 200-char head — the scar stays visible.

    PYTHONPATH=. .venv/bin/python tools/m4_lme_purge.py --dry-run
    PYTHONPATH=. .venv/bin/python tools/m4_lme_purge.py --extra-ids 135624,196911
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from serve.memory import attach, MemoryService                        # noqa: E402

WORD = re.compile(r"[a-z0-9]+")


def norm(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def ngrams(tokens: list[str], n: int) -> set[tuple]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def corpus_6grams(path: str) -> tuple[set, int]:
    """Every word 6-gram in the LME corpus (sessions + questions + answers)."""
    data = json.load(open(path))
    items = data if isinstance(data, list) else data.get("items") or []
    toks: list[str] = []
    for it in items:
        chunks = []
        for s in (it.get("haystack_sessions") or []):
            msgs = s if isinstance(s, list) else [s]
            chunks += [str(m.get("content", "")) for m in msgs if isinstance(m, dict)]
        for k in ("question", "answer"):
            v = it.get(k)
            chunks.append(str(v) if v is not None else "")
        toks += norm(" ".join(chunks))
    return ngrams(toks, 6), len(items)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=os.environ.get("STRATA_STORE", "/home/eugene/Strata-data/memory-eval"))
    ap.add_argument("--corpus", default=os.environ.get(
        "LME_CORPUS", os.path.expanduser("~/Strata-data/bench/longmemeval_oracle.json")))
    ap.add_argument("--extra-ids", default="", help="comma list of ids the owner named")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", type=int, default=25)
    a = ap.parse_args()

    grams, n_items = corpus_6grams(a.corpus)
    print(f"corpus: {n_items} questions, {len(grams):,} distinct 6-grams from {a.corpus}")

    conn = attach(a.dir)
    # DEAD-TURN: provenance carries a turn_id (the harvest's stamp) and that turn is gone.
    # Provenance without a turn_id (manual rows) is never flagged by this rule.
    rows = conn.execute(
        "SELECT m.id, m.class, m.text, m.provenance, "
        "       NOT EXISTS (SELECT 1 FROM turns t WHERE t.id::text = m.provenance->>'turn_id') "
        "FROM memories m "
        "WHERE m.invalid_at IS NULL AND m.source NOT LIKE 'doc-index%%' "
        "  AND m.provenance ? 'turn_id' ORDER BY m.id").fetchall()
    conn.close()

    flagged: dict[int, str] = {}
    for rid, cls, text, prov, dead in rows:
        if dead:
            flagged[rid] = "dead-turn"
        elif len(ngrams(norm(text), 6) & grams) >= 2:
            flagged[rid] = "6-gram"
        p = json.dumps(prov or {}).lower()
        if "lme" in p:
            flagged[rid] = flagged.get(rid, "lme-stamp")
    extra = {int(x) for x in a.extra_ids.split(",") if x.strip()}
    union = sorted(set(flagged) | extra)
    why = Counter = {}
    for rid in flagged:
        Counter[flagged[rid]] = Counter.get(flagged[rid], 0) + 1
    print(f"flagged {len(flagged)} by rule: {Counter}")
    print(f"extra-ids {len(extra)}   union to purge: {len(union)}")
    for rid in union[:a.sample]:
        print(f"  #{rid} {flagged.get(rid, 'owner-named')}")

    if a.dry_run:
        print("dry run, nothing written")
        return
    svc = MemoryService(a.dir)
    n = 0
    for rid in union:
        if svc.purge(rid, reason="LME test data, hard-deleted 2026-11-16"):
            n += 1
    print(f"purged {n} rows (embeddings went with them; the purges ledger keeps the scars)")


if __name__ == "__main__":
    main()
