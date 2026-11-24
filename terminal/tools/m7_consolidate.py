#!/usr/bin/env python3
"""Collapse near-duplicate facts into one survivor each (the retroactive supersession pass).

The store accumulates paraphrases of the same claim - the measurement law ended up with 46
active copies, the RTX 4090 with four. This tool clusters active rows by their own stored
vectors (cosine >= --threshold, greedy, newest id seeds each cluster), picks the survivor per
cluster (the fullest text, ties to the newest), and - with --go - retires every other member
through the LIVE server's /memory op:invalidate with by=survivor, so each drop lands as a
version-chain edge (invalid_at + superseded_by) and the server's own invalidate() dirties its
in-memory vector matrix (the raw-SQL route would leave the matrix offering superseded facts).

Dry run by default: prints what would move and nothing changes. Take a backup first
(tools/m6_backup.py); the invalidate is recall-invisible but history-visible, and the dump
makes even that undoable. Law (ADR-002 evening amendment, fact 3820): corrections are NOT
this tool's business - a cluster whose members disagree in fact, not just in words, belongs
to the curation sweep, which amends the survivor to carry the history before invalidating.
0.85 is the measured-safe threshold here (2026-10-16: 210 clusters / 421 rows, every sampled
cluster a true paraphrase); loosening it folds related-but-different facts.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from serve import memory as M  # noqa: E402


def cluster(rows, threshold):
    """Greedy cosine clusters at >= threshold. THE SURVIVOR IS THE FULLEST TEXT, ties to the newest
    (the docstring's law, and the code did not keep it - audit 2026-11-07: it kept the newest seed,
    so a cluster of "engine = 0.1.58" beside a one-line "engine is new" retired the richer row).
    The seed walk stays newest-first, which is what makes an unclaimed cluster cheap to find."""
    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]
    V = np.array([np.frombuffer(r[2], dtype=np.float32) for r in rows])
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    S = V @ V.T
    claimed = np.zeros(len(rows), bool)
    out = []
    for i in sorted(range(len(ids)), key=lambda i: -ids[i]):
        if claimed[i]:
            continue
        members = [j for j in np.argsort(-S[i]) if S[i][j] >= threshold and not claimed[j] and j != i]
        claimed[i] = True
        for j in members:
            claimed[j] = True
        keep = max([i] + members, key=lambda j: (len(texts[j]), ids[j]))
        rest = [j for j in members if j != keep]
        if keep != i and i in rest:
            rest.remove(i)
        if rest:
            out.append((keep, rest))
    dupes = [(ids[i], texts[i], [ids[j] for j in mem]) for i, mem in out]
    return dupes


def ladder(rows, hi=0.95, lo=0.80, cap_per_label=500, cap_per_request=10):
    """A resolution LADDER with a bound you can report (2026-11-24, item 16 — agentic-graphrag's
    `zone_classifier` + `resolver`). One cosine threshold is one ruler: at 0.85 every sampled
    cluster was a true paraphrase, and everything between 0.80 and 0.95 is a judgement. The ladder
    spends the cheap tests first and hands the model only the residue, in bands:

      1. SAME LABEL      — a fact on `HW` and a fact on `POL` are about different things;
      2. EXACT           — the normalized texts agree: certain, no model;
      3. NAME GATE       — the digit sets disagree ("48 layers" vs "12 layers"): certain NOT;
      4. FUZZY >= 0.97   — the token sets nearly agree: certain;
      5. EMBEDDING >= hi — certain; between lo and hi — AMBIGUOUS, the model's to decide;
      6. under lo        — not a pair at all.

    Three things the shape buys that a threshold cannot: a **cost bound you can state**
    (`ceil(ambiguous / cap_per_request)` asks, after `cap_per_label` pairs per label are dropped),
    a **report** (`cap_truncated_pairs`, `ambiguous_count` — the numbers the run leaves behind),
    and **undecided is not rejected**: a pair the model did not reach stays active, unjudged,
    visible. Greedy cosine today folds a pair and never says which band it came from.

    Pure over `rows` = (id, text, vec, class), so it tests with no server and no model.
    """
    import re
    from collections import defaultdict

    n = len(rows)
    ids = [r[0] for r in rows]
    norm = [re.sub(r"\s+", " ", str(r[1]).casefold()).strip() for r in rows]
    digits = [frozenset(re.findall(r"\d+", norm[i])) for i in range(n)]
    toks = [set(re.findall(r"[\w']+", norm[i])) for i in range(n)]
    V = np.array([np.frombuffer(r[2], dtype=np.float32) for r in rows])
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    S = V @ V.T
    by_label: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    stats = {"pairs": 0, "exact": 0, "name_gate": 0, "fuzzy": 0, "embedding": 0,
             "not_a_pair": 0, "cap_truncated_pairs": 0, "ambiguous_count": 0,
             "llm_requests": 0, "undecided": 0}
    for i in range(n):
        for j in range(i + 1, n):
            a, b = (str(rows[i][3] or ""), str(rows[j][3] or ""))
            if a and b and a.split("/")[0] != b.split("/")[0]:
                continue                                  # rung 1: different shelves, different facts
            cos = float(S[i][j])
            if cos < lo:
                stats["not_a_pair"] += 1
                continue
            stats["pairs"] += 1
            if norm[i] == norm[j]:
                stats["exact"] += 1
                by_label[a].append((ids[i], ids[j], cos))
                continue
            if digits[i] and digits[j] and digits[i] != digits[j]:
                stats["name_gate"] += 1
                continue                                   # rung 3: the numbers disagree, certain NOT
            uni = toks[i] | toks[j]
            if uni and len(toks[i] & toks[j]) / len(uni) >= 0.97:
                stats["fuzzy"] += 1
                by_label[a].append((ids[i], ids[j], cos))
                continue
            if cos >= hi:
                stats["embedding"] += 1
                by_label[a].append((ids[i], ids[j], cos))
                continue
            stats["ambiguous_count"] += 1
            by_label[a].append((ids[i], ids[j], cos))      # the model's to decide
    # The cap bounds the LLM WORK, so it applies to the ambiguous residue, band by band: the
    # certain pairs cost nothing and are never cut. Tightest first, so what survives a cut is the
    # best-evidenced half of the band.
    certain, to_ask = [], []
    for label, pairs in by_label.items():
        cert = [p for p in pairs if p[2] >= hi]
        amb = sorted([p for p in pairs if p[2] < hi], key=lambda p: -p[2])
        keep = amb[:cap_per_label]
        stats["cap_truncated_pairs"] += len(amb) - len(keep)
        certain.extend(cert)
        to_ask.extend(keep)
    stats["llm_requests"] = -(-len(to_ask) // cap_per_request) if to_ask else 0
    stats["undecided"] = len(to_ask)                        # not reached, not rejected
    return certain, to_ask, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, help="the store directory")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--url", default="http://127.0.0.1:8005/memory",
                    help="the live server's /memory endpoint (invalidations route through it)")
    ap.add_argument("--go", action="store_true", help="apply; default is a dry run")
    ap.add_argument("--ladder", action="store_true",
                    help="run the bounded resolution ladder (item 16) instead of one cosine "
                         "threshold: label gate, exact, name gate, fuzzy, then the embedding "
                         "bands, with the LLM bound and the cuts reported")
    ap.add_argument("--cap-label", type=int, default=500,
                    help="--ladder: ambiguous pairs kept per shelf before the cut")
    ap.add_argument("--cap-request", type=int, default=10,
                    help="--ladder: pairs per model request (the bound is ceil(this))")
    args = ap.parse_args()

    conn = M.attach(args.dir)
    # FACTS ONLY (audit 2026-11-07): the corpus is a ROUTING MAP, and 33k chunk rows are not
    # paraphrases of each other - the pass clustered 4,000 sampled chunks into 721 clusters
    # (1,693 rows to retire, 42%) because 73% of them share print typography. The matrix is the
    # other half of the bill: 35,462 rows is a 5.03 GB S = V@V.T on a 125 GB box.
    rows = conn.execute("""SELECT m.id, m.text, e.vec, coalesce(m.class, '') FROM memories m
                           JOIN embeddings e ON e.id = m.id
                           WHERE m.invalid_at IS NULL and """ + M.DOC_FACT_SQL).fetchall()
    conn.close()
    if args.ladder:
        # The ladder does not retire anything by itself: it says what is CERTAIN (fold these, no
        # model) and what is AMBIGUOUS (ask the model, within the bound), and reports the bound it
        # spent. `undecided` pairs stay active and unjudged — undecided is not rejected.
        certain, to_ask, st = ladder(rows, cap_per_label=args.cap_label,
                                     cap_per_request=args.cap_request)
        print(json.dumps(st, indent=1))
        print(f"{len(rows)} active fact rows with vectors")
        print(f"certain pairs {len(certain)} (no model) · ambiguous {len(to_ask)} "
              f"→ ≤{st['llm_requests']} requests of {args.cap_request} pairs")
        print(f"rung counts: exact {st['exact']} · fuzzy {st['fuzzy']} "
              f"· embedding≥{0.95} {st['embedding']} · name gate {st['name_gate']} "
              f"· not pairs {st['not_a_pair']}")
        print(f"cap cut {st['cap_truncated_pairs']} pairs at {args.cap_label}/shelf; "
              f"{st['undecided']} left undecided (active, unjudged)")
        return 0
    dupes = cluster(rows, args.threshold)
    purge = sum(len(d[2]) for d in dupes)
    print(f"{len(rows)} active rows with vectors; threshold {args.threshold}: "
          f"{len(dupes)} clusters, {purge} rows to retire, {len(dupes)} survivors kept")
    for sid, text, drops in sorted(dupes, key=lambda d: -len(d[2]))[:6]:
        print(f"\nKEEP {sid}: {text[:85]}")
        for j in drops[:3]:
            print(f"  drop {j}")
    if not args.go:
        print("\ndry run - nothing changed; pass --go to apply through the live server")
        return 0

    done = failed = held = 0
    for sid, _, drops in dupes:
        for j in drops:
            body = json.dumps({"op": "invalidate", "id": j, "by": sid}).encode()
            req = urllib.request.Request(args.url, data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    got = json.loads(r.read())
                # A PINNED ROW IS NOT A FAILURE (2026-10-29). m7 clusters by cosine and retires
                # everything but the keeper; a person's pin is a different kind of evidence than a
                # distance, so a refusal counts as HELD, not as a broken run.
                if got.get("invalidated"):
                    done += 1
                elif got.get("pinned"):
                    held += 1
                else:
                    failed += 1
            except Exception as e:  # noqa: BLE001 - one bad row must not stop the pass
                failed += 1
                print(f"  ! {j} -> {sid}: {e}")
    print(f"\napplied: {done} retired with superseded_by chains, {held} held by a pin, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
