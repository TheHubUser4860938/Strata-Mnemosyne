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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from serve.memory import (MemoryService, store_dbname,                  # noqa: E402
                          _CITE_FILE_RE as _FILE_TOKEN_RE,
                          _REMOTE_RE as _REMOTE_TOKEN_RE)
from serve.codegraph import default_graph                               # noqa: E402

MANIFEST = ".strata-vault.json"
REPO_GRAPH = Path(__file__).resolve().parents[2] / "graphify-out" / "graph.json"
SLUG_RE = re.compile(r"[^a-z0-9 .'-]+")
DOC_SCOPES = ("doc-founding", "doc-rustprobe")
# graphify's exporter names a note by `_obsidian_safe_stem(node.label)` at the vault ROOT. The
# rules ported (2026-11-24): strip the filesystem-unsafe set, strip a trailing .md-family
# extension, and prefix a leading dot with `dot-` (Obsidian hides dot files). Matching that rule
# is the whole point: a fact note that links `[[MemoryService]]` lands on graphify's code note in
# the SAME vault, and the graph pane draws an edge between a decision and a function.
UNSAFE_RE = re.compile(r'[\\/*?:"<>|#^\[\]]')


def stem(label: str) -> str:
    """The note name graphify would give this label — one rule, two exporters."""
    cleaned = UNSAFE_RE.sub("", str(label or "").replace("\r", " ").replace("\n", " ")).strip()
    cleaned = re.sub(r"\.(md|mdx|qmd|markdown)$", "", cleaned, flags=re.IGNORECASE)
    if cleaned.startswith("."):
        cleaned = "dot-" + cleaned.lstrip(".")
    return cleaned or "untitled"


def concepts_of(store_dir: str) -> dict[int, list[str]]:
    """fact row id → the concept labels it touches, read from the store's OWN graph
    (`<store>/strata-graphify/graph.json`, built by the served model's LLM pass).

    The concepts are the reason that graph exists: two rows that name the same subject and share no
    words. Projected as notes they are the vault's middle layer — a concept note is a table of
    contents for a subject no single row owns.
    """
    p = Path(store_dir) / "strata-graphify" / "graph.json"
    try:
        g = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    label = {str(n.get("id")): str(n.get("label") or n.get("id")) for n in g.get("nodes") or []}
    out: dict[int, list[str]] = {}
    for e in g.get("edges") or g.get("links") or []:
        a = str(e.get("source") or e.get("a") or "")
        b = str(e.get("target") or e.get("b") or "")
        for x, y in ((a, b), (b, a)):
            i = x.rfind("_fact_")
            if i >= 0 and x[i + 6:].isdigit() and "_fact_" not in y:
                out.setdefault(int(x[i + 6:]), []).append(label.get(y, y))
    return {k: list(dict.fromkeys(v))[:6] for k, v in out.items()}


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
    if row.get("concepts"):
        # The middle layer: this row's subject, as the memory graph named it. The note is written
        # by the same run, so the link is never a dead end.
        body += ["## Concepts", ""]
        body += [f"- [[_CONCEPT {stem(c)}|{c}]]" for c in row["concepts"]]
        body.append("")
    if row.get("code"):
        # The join to the repo graph. The target is graphify's note in this vault (its exporter
        # names notes by node label at the root), so the edge is real in the graph pane.
        body += ["## Code", ""]
        body += [f"- [[{stem(c.get('label') or c.get('node', ''))}|{c.get('label', '')}]]"
                 f" · `{c.get('file', '')}`" for c in row["code"]]
        body.append("")
    related = [r for c in (row.get("code") or []) for r in (c.get("related") or [])]
    if related:
        # The embedding edges: what the ruler says is near the cited code, one hop out.
        seen_r, lines = set(), []
        for r in related:
            key = r.get("node")
            if key in seen_r:
                continue
            seen_r.add(key)
            lines.append(f"- [[{stem(r.get('label') or key)}]] · `{r.get('file', '')}`"
                         f" · cos {r.get('cos')}")
        body += ["## Related by meaning", ""] + lines + [""]
    if row.get("scar"):
        body += ["## Earlier states", ""]
        body += [f"- {s}" for s in row["scar"]]
        body.append("")
    return "\n".join(body)


def concept_notes(concepts: dict[int, list[str]], rows_by_id: dict[int, dict]) -> dict[str, str]:
    """One note per concept: the rows that touch it, newest first, capped so a hub concept (the
    graph has 2,015 concept nodes over 2,352 facts) does not swallow the vault."""
    inv: dict[str, list[int]] = {}
    for rid, labs in concepts.items():
        if rid not in rows_by_id:
            continue        # the graph outlives the rows: a superseded fact has no note to link
        for c in labs:
            inv.setdefault(c, []).append(rid)
    out = {}
    for c, ids in inv.items():
        ids = sorted(ids, key=lambda i: str(rows_by_id.get(i, {}).get("when") or ""),
                     reverse=True)[:24]
        lines = ["---", f"concept: {stem(c)}", f"facts: {len(ids)}", "---",
                 f"# {c}", "", "Rows in the store that touch this subject:", ""]
        lines += [f"- [[{note_name(i, rows_by_id[i]['text'])[:-3]}|{i}]]"
                  f" · {(rows_by_id.get(i, {}).get('text') or '')[:110]}" for i in ids]
        out[f"_CONCEPT {stem(c)}.md"] = "\n".join(lines) + "\n"
    return out


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


def project(out: Path, rows: list[dict], linkmap: dict, *, apply: bool = True,
            extra: dict[str, str] | None = None) -> dict:
    """Write the vault. Returns the tally: written, unchanged, pruned, owned.

    `extra` is the second tier — concept notes, in today's build — written into the vault root and
    owned by the manifest exactly like a fact note, so a prune takes an abandoned concept with it.
    """
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
    for name, text in (extra or {}).items():
        fresh.add(name)
        target = out / name
        if not apply:
            continue
        if target.exists() and target.read_text(encoding="utf-8") == text:
            same += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written += 1
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


def code_notes(graph_path: Path, cited: list[str], limit: int = 900) -> dict[str, str]:
    """The code tier, filtered to what the store talks about (2026-11-24, the merge).

    graphify's own vault export writes one note per node — 188,753 notes, 822 MB on this repo
    (measured), which is the whole graph and more vault than a person can read. The store cites a
    few hundred of those nodes, so the tier this projection writes is the CITED set plus one hop of
    neighbours: the code notes a fact link to, and the structure around them.

    Names follow `stem()` — graphify's rule — so a `[[MemoryService]]` link from a fact note
    resolves in either vault, and a reader who wants the full graph can run graphify's export
    beside it.
    """
    try:
        g = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    nodes = {str(n.get("id")): n for n in g.get("nodes") or []}
    sem: dict[str, list[tuple[str, float]]] = {}
    try:  # the embedding sidecar: a code note's "Related by meaning" section
        doc = json.loads((graph_path.parent / "semantic.json").read_text(encoding="utf-8"))
        for p in doc.get("pairs") or []:
            a, b, c = str(p.get("source") or ""), str(p.get("target") or ""), float(p.get("cos") or 0)
            if a and b:
                sem.setdefault(a, []).append((b, c))
                sem.setdefault(b, []).append((a, c))
        for v in sem.values():
            v.sort(key=lambda x: -x[1])
    except (OSError, ValueError):
        pass
    want: dict[str, None] = {}
    for nid in cited:
        if nid in nodes:
            want.setdefault(nid)
    adj: dict[str, list[str]] = {}
    for e in g.get("edges") or g.get("links") or []:
        a, b = str(e.get("source") or e.get("a") or ""), str(e.get("target") or e.get("b") or "")
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    for nid in list(want):
        for x in adj.get(nid, [])[:12]:
            if len(want) >= limit:
                break
            if x in nodes:
                want.setdefault(x)
    out = {}
    for nid in want:
        n = nodes.get(nid)
        if not n:
            continue
        label = str(n.get("label") or nid)
        nb = [x for x in adj.get(nid, []) if x in nodes][:18]
        rel = [(x, c) for x, c in sem.get(nid, [])[:6] if x in nodes]
        lines = ["---", f"node: {nid}", f"label: {stem(label)}",
                 f"file: {n.get('source_file') or ''}",
                 f"loc: {n.get('source_location') or ''}",
                 f"type: {n.get('type') or n.get('kind') or ''}", "---",
                 f"# {label}", ""]
        if n.get("docstring") or n.get("summary"):
            lines += [str(n.get("docstring") or n.get("summary"))[:600], ""]
        if rel:
            lines += ["## Related by meaning", ""]
            lines += [f"- [[{stem(str(nodes[x].get('label') or x))}]] · cos {c}" for x, c in rel]
            lines.append("")
        if nb:
            lines += ["## Neighbours", ""]
            lines += [f"- [[{stem(str(nodes[x].get('label') or x))}]]" for x in nb]
            lines.append("")
        out[f"code/{stem(label)}.md"] = "\n".join(lines) + "\n"
    return out


def pull(out: Path, svc) -> dict:
    """The one-way projection, reversed (2026-11-24, the merge): a human edit in Obsidian becomes a
    row.

    The rule is the store's own — never erase, annotate: an edited note does not overwrite its row,
    it SUPERSEDES it, so the chain and the scar survive and the vault's next run writes the new
    text back to the same note name. The id is the join (the note's `id:` frontmatter is the row
    id, which is why the filename carries it too).

    Only notes the manifest owns are read, so a hand-written note that shares a folder is left
    alone as a note, not turned into a fact.
    """
    mpath = out / MANIFEST
    if not mpath.exists():
        return {"pulled": 0, "error": f"no manifest at {mpath}"}
    files = json.loads(mpath.read_text(encoding="utf-8")).get("files", [])
    pulled = []
    for f in files:
        p = out / f
        if not p.exists() or f.startswith("_CONCEPT"):
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^id: (\d+)\s*$", text, re.M)
        if not m:
            continue
        rid = int(m.group(1))
        body = text.split("---", 2)
        if len(body) < 3:
            continue
        note = body[2].split("## ", 1)[0].strip()      # the fact text, before the link sections
        cur = svc.conn.execute("select text from memories where id = %s", (rid,)).fetchone()
        svc.conn.commit()
        # Compare LINES, not raw bytes: the harvest's text carries a trailing newline and
        # can fold long sentences; the note is that text, one strip removed. A human edit
        # changes a line; projection noise does not.
        def norm(s):
            return "\n".join(ln.rstrip() for ln in str(s or "").strip().splitlines())
        if cur is None or norm(note) == norm(cur[0]):
            continue
        r = svc.remember(note, scope=cur and "default", klass=None)
        if r.get("id") and cur is not None:
            svc.invalidate(rid, by_id=r["id"])
        pulled.append({"id": rid, "new": r.get("id"), "note": f})
    return {"pulled": len(pulled), "rows": pulled[:8]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the vault folder")
    ap.add_argument("--dir", default=os.environ.get("STRATA_STORE",
                                                    "/home/eugene/Strata-data/memory-eval"))
    ap.add_argument("--limit", type=int, default=0, help="project the newest N facts (0 = all)")
    ap.add_argument("--dry", action="store_true", help="count what would move, write nothing")
    ap.add_argument("--lint", action="store_true", help="check the vault on disk, then exit")
    ap.add_argument("--pull", action="store_true",
                    help="read the vault back: a note a human edited supersedes its row (the "
                         "chain survives; the next projection writes the new text to the note)")
    ap.add_argument("--concepts", action="store_true",
                    help="write the middle tier: one note per concept the store's own graph names, "
                         "linked from every row that touches it (default on)")
    ap.add_argument("--no-concepts", action="store_true", help="skip the concept tier")
    ap.add_argument("--graph", default=str(REPO_GRAPH),
                    help="graphify's repo graph, for the code tier")
    ap.add_argument("--no-code", action="store_true",
                    help="skip the code tier (the notes the facts link to, and one hop)")
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
        " provenance, superseded_by, coalesce(superseded_by, 0) from memories"
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
    cg = default_graph()                       # the row↔code seam (serve/codegraph.py)
    concepts = {} if a.no_concepts else concepts_of(a.dir)
    for r in rows:
        prov = r[8] or {}
        when = r[6].strftime("%Y-%m-%d %H:%M") if r[6] else ""
        cites = [n for n in _FILE_TOKEN_RE.findall(r[1] or "") if not _REMOTE_TOKEN_RE.match(n)]
        code = []
        for nm in cites[:2]:                   # two files per note: the join, not a wall of links
            res = cg.resolve(nm)
            code += res["nodes"][:3]
        facts.append({"id": int(r[0]), "text": r[1], "class": r[2], "scope": r[3],
                      "confidence": r[4], "proof": int(prov.get("proof") or 0),
                      "when": when, "filed": "", "stale": bool(prov.get("stale")),
                      "why": prov.get("why") or "", "scar": prov.get("scar") or [],
                      "code": code[:4], "concepts": concepts.get(int(r[0]), []),
                      "supersedes": (f"[[{note_name(int(prov['supersedes']), '')[:-3]}]]"
                                     if str(prov.get("supersedes") or "").isdigit() else ""),
                      "superseded_by": (f"[[{note_name(int(r[9]), '')[:-3]}]]" if r[9] else "")})
    extra = {}
    if concepts:
        extra = concept_notes(concepts, {f["id"]: f for f in facts})
    if not a.no_code:
        cited = [c["node"] for f in facts for c in f.get("code") or []]
        cited += [r["node"] for f in facts for c in f.get("code") or []
                  for r in (c.get("related") or [])]      # the semantic hop, one out
        extra.update(code_notes(Path(a.graph), list(dict.fromkeys(cited))))
    if a.pull:
        print(json.dumps(pull(out, svc), indent=1))
        svc.close()
        return 0
    tally = project(out, facts, linkmap, apply=not a.dry, extra=extra)
    print(json.dumps(tally, indent=1))
    print(f"vault → {out}  ({'dry run' if a.dry else 'written'})"
          + (f" · {len(extra)} concept notes · {sum(1 for f in facts if f['code'])} rows joined"
             f" to code" if extra else ""))
    svc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
