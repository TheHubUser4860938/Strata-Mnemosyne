#!/usr/bin/env python3
"""m10_vault.py — the store, projected one-way into an Obsidian vault (2026-11-24, item 13).

Obsidian's unit is the file: the note is the identity and the index is a cache — the mirror of
Strata, where the row is the identity and the vault is a view. This is the human-shaped projection
of the standing text: what the cartridge is to the K/V cache. Retrieval stays in Postgres.

    PYTHONPATH=. .venv/bin/python tools/m10_vault.py --out ~/vaults/strata [--dir STORE]
    PYTHONPATH=. .venv/bin/python tools/m10_vault.py --out ~/vaults/strata --lint

Three semantics, all borrowed from graphify's Obsidian exporter because they are proven and
byte-stable:

  * a MANIFEST of the files this tool owns (`.strata-vault.json`), so a second run is a no-op
    and a pruned row's note goes away;
  * `_owned_write`: a file that exists and is NOT in the manifest is a human's note — leave it,
    never clobber it;
  * write only when the bytes changed, so the vault's "modified" sort stays meaningful.

The shapes:

  shelf → folder      `OPS/SWEEP.md` under `OPS/`, `DOC/*` excluded (33k chunk rows are a routing
                      map, not a reading shelf)
  row → note          the filename carries the id, so a note is addressable and stable across edits
  supersede → link    `supersedes: "[[4545 the soul.md feature…]]"`, and the chain is the graph
  links → wikilinks   in frontmatter (`relations:`) AND a `## Connections` bullet list, because
                      the graph pane draws the bullets, not the properties
  two `.base` files   the ledger (shelf × confidence × proof) and the supersession chain — a `.base`
                      is YAML with filters/formulas/views over the WHOLE vault (no `from` clause:
                      a base includes every file, which is why each view filters by folder)
  a lint, not a schema  a fact note with no `when`, no `shelf`, or a `supersedes:` pointing at a
                      file that is not in the vault fails the run

Measured on this box's earlier export of 212,916 notes: 91.0 MB of text occupying 888 MB on disk,
in a flat directory. The shelf folders are the answer to the flatness; the facts-only filter is the
answer to the size.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from serve.memory import MemoryService, USER_SCOPE, store_dbname     # noqa: E402

MANIFEST = ".strata-vault.json"
SLUG_RE = re.compile(r"[^a-z0-9 .'-]+")
DOC_SCOPES = ("doc-founding", "doc-rustprobe")


def slug(text: str, limit: int = 44) -> str:
    s = SLUG_RE.sub(" ", str(text or "").casefold())
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return (s[:limit].rsplit(" ", 1)[0] if len(s) > limit else s) or "note"


def note_name(rid: int, text: str) -> str:
    return f"{rid} {slug(text)}.md"


def front(row: dict, links: list[dict]) -> str:
    """YAML frontmatter. Hand-written, not pyyaml: the store's own vocabulary is small, and a
    projection that needs a dependency to say what a fact is, is a dependency for a string."""
    def esc(v):
        return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'
    lines = ["---",
             f"id: {row['id']}",
             f"shelf: {esc(row.get('class') or '')}",
             f"scope: {esc(row.get('scope') or '')}",
             f"when: {esc(row.get('when') or '')}"]
    if row.get("filed"):
        lines.append(f"filed: {esc(row['filed'])}")
    if row.get("confidence") is not None:
        lines.append(f"confidence: {float(row['confidence']):.2f}")
    if row.get("proof"):
        lines.append(f"proof: {int(row['proof'])}")
    if row.get("stale"):
        lines.append("stale: true")
    if row.get("supersedes"):
        lines.append(f"supersedes: {esc(row['supersedes'])}")
    if row.get("superseded_by"):
        lines.append(f"superseded_by: {esc(row['superseded_by'])}")
    if row.get("why"):
        lines.append(f"why: {esc(row['why'])}")
    if row.get("scar"):
        lines.append("scar:")
        lines += [f"  - {esc(s)}" for s in row["scar"]]
    if links:
        lines.append("relations:")
        for l in links:
            lines.append(f"  - {esc(l['kind'] + ' ' + l['target'])}")
    lines.append("---")
    return "\n".join(lines)


def note_body(row: dict, links: list[dict]) -> str:
    body = [front(row, links), "", str(row.get("text") or "").strip(), ""]
    if links:
        body += ["## Connections", ""]
        body += [f"- {l['kind']} → {l['target']}" for l in links]
        body.append("")
    if row.get("scar"):
        body += ["## Earlier states", ""]
        body += [f"- {s}" for s in row["scar"]]
        body.append("")
    return "\n".join(body)


BASE_LEDGER = """filters:
  and:
    - file.ext == "md"
    - shelf != ""
views:
  - type: table
    name: Ledger
    order:
      - file.name
      - shelf
      - confidence
      - proof
      - when
    limit: 50
"""

BASE_CHAIN = """filters:
  and:
    - file.ext == "md"
    - supersedes != ""
views:
  - type: table
    name: Supersession chain
    order:
      - file.name
      - supersedes
      - when
"""

HOME = """---
title: Strata Mnemosyne
---

# The store, as a vault

Facts are notes; a shelf is a folder; a supersession is a link. This vault is a **one-way
projection** of the Postgres store — edit the row, re-run the exporter, the note follows. The
notes the exporter owns are listed in `.strata-vault.json`; anything else in here is yours and
the run leaves it alone.

- [[facts.base]] — the ledger: shelf, confidence, proof, when.
- [[chain.base]] — the supersession chain: every belief that replaced one.

Retrieval lives in Postgres (`memory_search`). The graph pane draws `## Connections`.
"""


def project(out: Path, rows: list[dict], linkmap: dict, *, apply: bool = True) -> dict:
    """Write the vault. Returns the tally: written, unchanged, pruned, owned."""
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / MANIFEST
    owned: set[str] = set()
    if mpath.exists():
        owned = set(json.loads(mpath.read_text(encoding="utf-8")).get("files", []))
    fresh: set[str] = set()
    written = same = 0
    for r in rows:
        rel = os.path.join(str(r.get("class") or "WILD").split("/")[0], note_name(r["id"], r["text"]))
        rel = rel.replace(os.sep, "/")
        fresh.add(rel)
        target = out / rel
        body = note_body(r, linkmap.get(r["id"], []))
        if not apply:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and rel not in owned:
            # A human's note wearing a name we would have used: theirs stands (the ownership rule
            # graphify's exporter proved on 212,916 notes). The row is not lost — it re-appears
            # next to it, because the filename carries the id and ids are unique.
            rel = f"{rel}.strata.md"
            fresh.add(rel)
            target = out / rel
        if target.exists() and target.read_text(encoding="utf-8") == body:
            same += 1
            continue
        target.write_text(body, encoding="utf-8")
        written += 1
    pruned = []
    for rel in sorted(owned - fresh):
        p = out / rel
        if p.exists():
            if apply:
                p.unlink()
            pruned.append(rel)
    if apply:
        (out / "facts.base").write_text(BASE_LEDGER, encoding="utf-8")
        (out / "chain.base").write_text(BASE_CHAIN, encoding="utf-8")
        (out / "Home.md").write_text(HOME, encoding="utf-8")
        mpath.write_text(json.dumps({"files": sorted(fresh), "rows": len(rows)}, indent=1),
                         encoding="utf-8")
    return {"rows": len(rows), "written": written, "unchanged": same, "pruned": len(pruned),
            "pruned_paths": pruned[:8], "owned": len(fresh)}


def lint(out: Path) -> list[str]:
    """A lint, not a schema: the three mechanical failures that make a note useless in the graph."""
    bad: list[str] = []
    mpath = out / MANIFEST
    if not mpath.exists():
        return [f"no manifest at {mpath} — run the projection first"]
    files = json.loads(mpath.read_text(encoding="utf-8")).get("files", [])
    names = {Path(f).stem for f in files}
    for f in files:
        p = out / f
        if not p.exists():
            bad.append(f"{f}: in the manifest, not on disk")
            continue
        head = p.read_text(encoding="utf-8").split("---", 2)[1] if p.read_text(
            encoding="utf-8").startswith("---") else ""
        if "when: \"\"" in head or "\nwhen:" in head and "when: \"\"" in head:
            bad.append(f"{f}: no `when` — the note cannot be dated")
        if 'shelf: ""' in head:
            bad.append(f"{f}: no `shelf` — the note is wild")
        m = re.search(r'supersedes: "(.+?)"', head)
        if m:
            tgt = m.group(1).strip('"[]')
            if tgt and tgt not in names:
                bad.append(f"{f}: supersedes → {tgt!r}, which is not in the vault")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the vault folder")
    ap.add_argument("--dir", default=os.environ.get("STRATA_STORE",
                                                    "/home/eugene/Strata-data/memory-eval"))
    ap.add_argument("--limit", type=int, default=0, help="project the newest N facts (0 = all)")
    ap.add_argument("--dry", action="store_true", help="count what would move, write nothing")
    ap.add_argument("--lint", action="store_true", help="check the vault on disk, then exit")
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    if a.lint:
        bad = lint(out)
        for b in bad[:40]:
            print("LINT " + b)
        print(f"{len(bad)} lint finding(s)")
        return 1 if bad else 0

    uri = f"postgresql://postgres@/{store_dbname(a.dir)}?host={os.path.join(a.dir, 'pgdata')}&port=5432"
    svc = MemoryService(a.dir, pg_uri=uri)
    lim = f" limit {int(a.limit)}" if a.limit else ""
    rows = svc.conn.execute(
        "select id, text, coalesce(class,''), scope, confidence, coalesce(hits,0), created_at,"
        " provenance, superseded_by from memories"
        " where invalid_at is null and not (scope = any(%s))"
        f" order by created_at desc{lim}", (list(DOC_SCOPES),)).fetchall()
    svc.conn.commit()
    ids = [r[0] for r in rows]
    link_rows = svc.conn.execute(
        "select l.a_id, l.b_id, l.kind from links l where l.invalid_at is null"
        " and (l.a_id = any(%s) or l.b_id = any(%s))", (ids, ids)).fetchall()
    svc.conn.commit()
    by_id = {r[0]: r for r in rows}

    def wikilink(rid: int) -> str:
        r = by_id.get(rid)
        return f"[[{note_name(rid, r[1])[:-3]}]]" if r else f"[[missing {rid}]]"

    linkmap: dict[int, list[dict]] = {}
    for a_id, b_id, kind in link_rows:
        for me, other in ((a_id, b_id), (b_id, a_id)):
            linkmap.setdefault(int(me), []).append(
                {"kind": kind, "target": wikilink(int(other))})
    facts = []
    for r in rows:
        prov = r[8] or {}
        when = r[6].strftime("%Y-%m-%d %H:%M") if r[6] else ""
        facts.append({"id": int(r[0]), "text": r[1], "class": r[2], "scope": r[3],
                      "confidence": r[4], "proof": int(prov.get("proof") or 0),
                      "when": when, "filed": "", "stale": bool(prov.get("stale")),
                      "why": prov.get("why") or "", "scar": prov.get("scar") or [],
                      "supersedes": (f"[[{note_name(int(prov['supersedes']), '')[:-3]}]]"
                                     if str(prov.get("supersedes") or "").isdigit() else ""),
                      "superseded_by": (f"[[{int(r[8])}]]" if r[8] else "")})
    tally = project(out, facts, linkmap, apply=not a.dry)
    print(json.dumps(tally, indent=1))
    print(f"vault → {out}  ({'dry run' if a.dry else 'written'})")
    svc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
