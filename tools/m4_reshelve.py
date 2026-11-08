#!/usr/bin/env python3
"""m4_reshelve - sort the store against its own shelf map, with the model as the clerk.

2026-11-02, the owner's ask: "a lot of things need to be shifted around and put into
their categories, sub shelves and cutters". The census said how much: **583 of 2,226
fact rows (26%) are WILD** - no class at all, so they ride every unfiltered request
and join no filtered one - and the top-level shelves are piled (90 rows sit on the
bare `AI` cutter, 101 on `OPS`, 60 on `HW`, 33 on `DEC`) while the cutters under them
sit nearly empty (AI/HERME 3, DEC/POSTG 9).

The keyword map (tools/curate_loop.py, fact_class) shelves what it can name and leaves
the rest wild. This is the human-shaped pass over what it could not name: the served
model reads each fact against the store's OWN shelf list - names plus the MEM/CAT
labels, the same words the browse map shows a reader - and files it on one shelf,
opens `NEW/CUTTER`, or leaves it WILD.

A false shelf HIDES a fact from every filtered request that stops asking for it (the
50-group merge audit's law), so the rule is: PROPOSE, write a review log, apply only
with --apply. Every move is one `classify()` through the service, so the caches and the
vector matrix stay right (the 2026-10-16 backfill's lesson: a classify that does not
dirty the matrix leaves the cosine arm answering for the OLD shelf).

  python3 tools/m4_reshelve.py [--dir ~/Strata-data/memory-eval]
      [--class WILD|AI|OPS|...]     rows to sort: bare WILD, an exact shelf, or a
                                    prefix (OPS matches OPS and OPS/*)
      [--batch 8] [--limit N] [--min-rows 2]   the menu: shelves with >= N rows
      [--url http://127.0.0.1:8005/v1/chat/completions]
      [--apply]   write the moves (classify, op=classify's own path); default is dry
      [--out FILE] review log, JSONL (default ~/Strata-data/bench/m4-reshelve-<date>-<class>.jsonl)

Read the log before trusting a number: the clerk is a small local model, and a
plausible shelf is not a proven one.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "serve")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from strata_control.datafolder import data_dir                     # noqa: E402
from serve.memory import MemoryService, class_name                 # noqa: E402

PROMPT = """You are a librarian filing facts onto shelves. A shelf code is a call \
number: `MEM`, `OPS/STATE`, `DOC/FOUNDING`. Use the shelf whose SUBJECT the fact is \
about, not a shelf that merely shares a word.

Shelves (code - subject words):
{menu}

Rules:
- Prefer an existing shelf.
- If none fits and the fact belongs to a clear new subject, open `NEW/CUTTER` with a \
3-6 letter uppercase cutter (e.g. `NEW/PREFIL`).
- If the fact is miscellaneous, answer `WILD`.
- Reason as long as you like. Then END your reply with a section headed `FILE:` that \
holds exactly one line per fact, `<n>: <SHELF>`, and nothing after it.

Facts:
{facts}
"""
# The clerk's answer, read as a DECISION. The prompt asks for a trailing `FILE:`
# section - the clean read. This box's model also thinks out loud and QUOTES each fact,
# and a quotation begins "2. " too, so a code found in the prose is only trusted when it
# stands alone on its line ("I'd file this as\nOPS/STATE"), the shape a decision leaves.
ANSWER = re.compile(r"^\s*(\d+)\s*[:=]\s*([A-Z][A-Z0-9/]{1,15})\s*$", re.M)
SECTION = re.compile(r"FILE\s*:", re.M | re.I)
CODE = re.compile(r"\b([A-Z][A-Z0-9]{1,7}(?:/[A-Z0-9]{2,8})?)\b")


def ask_box(prompt: str, url: str, max_tokens: int = 1400, timeout: float = 180.0) -> str:
    """One clerk's turn on the served box.

    `{REASON:off}` is the box's own mute directive (curate_loop's shape), and the
    fallback into `reasoning_content` is the lesson of the first run: this model thinks
    by default, a 220-token budget spent entirely on thinking reads back as an EMPTY
    reply, and 40 rows all "unparsed" was that - not a bad prompt. The budget is
    1400 for the same reason: the clerk REASONS per fact and then files in a trailing
    `FILE:` section, so a short budget truncates the section, which is the half that
    matters. 700 tokens lost the FILE block on a 4-fact batch; 1400 finished it.
    """
    body = json.dumps({"model": "strata", "temperature": 0.0, "max_tokens": max_tokens,
                       "messages": [{"role": "user",
                                     "content": "{REASON:off}\n\n" + prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310
        data = json.loads(resp.read().decode())
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    return str(msg.get("content") or msg.get("reasoning_content") or "")


def menu_of(svc, min_rows: int) -> tuple[list[str], set[str]]:
    """The store's own shelf list, with the MEM/CAT label beside each name when one
    exists. The menu IS the vocabulary: the clerk may file on a shelf or open a cutter,
    and nothing else."""
    with svc.lock:
        rows = svc.conn.execute(
            "select coalesce(class,''), count(*) from memories where invalid_at is null"
            " and coalesce(scope,'') not like 'doc-%%' group by 1 order by 2 desc").fetchall()
        labels = {r[0].split(" - ")[0].strip().upper(): r[0].split(" - ", 1)[1].strip()
                  for r in svc.conn.execute(
                      "select text from memories where class='MEM/CAT'"
                      " and invalid_at is null").fetchall() if " - " in r[0]}
        svc.conn.commit()
    keep = [(c, n) for c, n in rows if c and n >= min_rows]
    menu = [f"{c} - {labels[c]}" if c in labels else f"{c} - ({n} rows)" for c, n in keep]
    return menu, {c for c, _n in keep}


def rows_to_sort(svc, which: str, limit: int) -> list[tuple[int, str, str]]:
    """The queue: WILD rows (no class), or everything on one shelf / shelf family."""
    sel, arg = ("(class is null or class='')", None)
    if which.upper() != "WILD":
        up = which.upper()
        sel, arg = ("(class = %s or class like %s)", (up, up + "/%"))
    params = list(arg) if arg is not None else []
    if limit:
        params.append(int(limit))
    q = ("select id, coalesce(class,''), text from memories"
         " where invalid_at is null and " + sel
         + " and coalesce(scope,'') not like 'doc-%%' order by id"
         + (" limit %s" if limit else ""))
    with svc.lock:
        rows = svc.conn.execute(q, params).fetchall()
        svc.conn.commit()
    return [(int(r[0]), r[1] or "", r[2]) for r in rows]


def _one(code: str, known: set[str]) -> tuple[str, str]:
    if not code or code == "WILD":
        return ("", "wild")
    if code in known:
        return (code, "existing")
    if "/" in code and not code.startswith("NEW/"):
        top, cut = code.split("/", 1)
        if top == cut:                       # TECH/TECH: one drawer, two name tags (2026-11-06)
            return (top, "existing") if top in known else (top, "unknown")
    if code.startswith("NEW/"):
        cut = code[4:]
        if not class_name(cut, quiet=True):
            return ("", "new")
        # A cutter that EXTENDS a name the menu already carries is the same drawer wearing a
        # longer truncation - USR/PREFE arriving beside USR/PREF, MEM/QWEN beside MEM/QWEN3
        # (census 2026-11-06). Prefix, do not mint, when exactly one shelf is in on it.
        fam, sep, cta = cut.rpartition("/")
        kin = [k for k in known
               if k.rpartition("/")[0] == fam and not k.startswith("NEW/")
               and (k.rpartition("/")[2].startswith(cta) or cta.startswith(k.rpartition("/")[2]))]
        if len(kin) == 1:
            return (kin[0], "existing")
        return ("NEW/" + cut, "new")
    kin = [k for k in known if "/" not in k and (k.startswith(code) or code.startswith(k))]
    if len(kin) == 1:
        return (kin[0], "existing")          # QWEN3 arriving where the menu carries QWEN
    return (code, "unknown")


def pick(answer: str, n: int, known: set[str], prose: str = "") -> dict[int, tuple[str, str]]:
    """One batch reply -> {fact number: (shelf, kind)}.

    kind: `existing` (on the menu), `new` (the clerk opened `NEW/CUTTER`), `wild`
    (stays miscellaneous), `unknown` (a code the menu does not carry - the reviewer
    judges it), `unparsed` (no answer for that fact, so it does not move).
    """
    text = answer or ""
    m = SECTION.search(text)
    tail = text[m.end():] if m else ""
    out: dict[int, tuple[str, str]] = {}
    for src in (tail, text, prose):                  # the FILE: section wins, then prose
        for g in ANSWER.finditer(src or ""):
            i = int(g.group(1))
            if 1 <= i <= n and i not in out:
                out[i] = _one(g.group(2).strip().upper(), known)
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(data_dir(ROOT) / "memory-eval"))
    ap.add_argument("--class", dest="klass", default="WILD",
                    help="WILD (no class), an exact shelf, or a prefix like OPS")
    ap.add_argument("--batch", type=int, default=6,
                    help="facts per clerk turn; each one costs reasoning tokens")
    ap.add_argument("--max-tokens", type=int, default=1400,
                    help="the clerk's budget per turn (it reasons, then files)")
    ap.add_argument("--limit", type=int, default=0, help="cap rows this pass (0 = all)")
    ap.add_argument("--min-rows", type=int, default=2, help="menu: shelves with >= N rows")
    ap.add_argument("--url", default="http://127.0.0.1:8005/v1/chat/completions")
    ap.add_argument("--apply", action="store_true", help="write the moves (classify)")
    ap.add_argument("--out", default="", help="review log (JSONL)")
    a = ap.parse_args()

    svc = MemoryService(a.dir)
    menu, known = menu_of(svc, a.min_rows)
    rows = rows_to_sort(svc, a.klass, a.limit)
    out = Path(a.out or str(data_dir(ROOT) / "bench" /
                            f"m4-reshelve-{time.strftime('%Y-%m-%d')}-{a.klass.lower()}.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"menu {len(menu)} shelves | queue {len(rows)} rows | "
          f"{'APPLY' if a.apply else 'dry run'} | log {out}")
    if not rows:
        svc.close()
        return 0
    tally, moved, t0 = Counter(), 0, time.time()
    with out.open("a", encoding="utf-8") as log:
        for i in range(0, len(rows), a.batch):
            chunk = rows[i:i + a.batch]
            facts = "\n".join(f"{j + 1}. {t[:300]}" for j, (_id, _c, t) in enumerate(chunk))
            ans = ask_box(PROMPT.format(menu="\n".join(menu), facts=facts), a.url,
                          max_tokens=a.max_tokens)
            got = pick(ans, len(chunk), known)
            for j, (mid, cur, text) in enumerate(chunk):
                new, kind = got.get(j + 1, ("", "unparsed"))
                tally[f"{kind}:{new or 'WILD'}"] += 1
                if new and new != cur and kind in ("existing", "new"):
                    # `unknown` is a PROPOSAL, not an address (audit 2026-11-07): a code off the
                    # menu used to be written, which is the pile the shelftidy pass exists to roll
                    # up - 25 invented tops in the 11-02 census.
                    moved += 1
                    log.write(json.dumps({"id": mid, "from": cur, "to": new, "kind": kind,
                                          "text": text[:200]}) + "\n")
                    log.flush()
                    if a.apply:
                        svc.classify(mid, new.replace("NEW/", ""))
            done = min(i + a.batch, len(rows))
            print(f"  {done}/{len(rows)} rows, {moved} moves "
                  f"({time.time() - t0:.0f} s)", flush=True)
    print(f"\nmoves proposed: {moved} of {len(rows)} rows"
          + ("  (APPLIED via classify)" if a.apply else "  (dry run - nothing written)"))
    for k, v in tally.most_common(16):
        print(f"  {v:4}  {k}")
    svc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
