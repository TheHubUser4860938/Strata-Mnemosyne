# Obsidian — the vault as a memory architecture (the ninth system)

**Read 2026-11-23.** Sources: `obsidianmd/obsidian-help@master/en/` (the help site is a SPA; the
repo is the source of truth, 181 English pages), `obsidianmd/obsidian-api@master/obsidian.d.ts`
(11,569 lines), JSON Canvas 1.0 spec (2024-03-11), the practitioners' own READMEs, and **a vault I
generated on this box** with the vendored exporter. Star counts from the GitHub API today.

**Why it is in this directory.** Not as a note app. As the pattern where **the file is the identity
and the index is a cache** — the mirror image of Strata, where Postgres is the identity and the
graph is a derived file (`<store>/strata-graphify/graph.json`).

## The format, in the parts that bear on memory

- **A vault is a folder.** "Obsidian stores your notes as Markdown-formatted plain text files in a
  *vault*. A vault is a folder on your local file system." App state lives in `.obsidian/`.
- **The index is disposable.** Obsidian keeps an IndexedDB metadata cache that "powers many things
  across the app, from the Graph view to the Outline view" and is rebuildable from the files. Grep
  works with the app closed.
- **Properties = typed YAML frontmatter.** Seven types (Text, List, Number, Checkbox, Date, Date &
  time, Tags), and the schema is **global per key, vault-wide, inferred**: "all properties with that
  name across your vault will use the same type". Three documented non-features: no nested
  properties, no bulk editing, no Markdown in properties — "an intentional limitation as properties
  are meant for small, atomic bits of information".
- **Links are the graph, and they are untyped.** The machine view is one API line:
  `resolvedLinks: Record<string, Record<string, number>>` — an edge carries a **count**, never a
  kind. `getFileCache()` returns a parse (`links, embeds, tags, headings, sections, listItems,
  frontmatter, blocks`), not a model. Graph-view Groups color *nodes by search term*, so an edge
  type is invisible in the graph view. Links resolve **by file name, not by alias**.
- **Search has no ranking.** Boolean word matching with operators (`file: path: content: tag:
  line: block: section: task:`) and property predicates (`[status]`, `[duration:<5]`), sorted by six
  mechanical options: name, modified, created. **No relevance score anywhere.**
- **Bases (1.9.10, release notes 2025-08-18) is the database layer, and it is a file.** A `.base` is
  YAML with `filters / formulas / properties / summaries / views` over the whole vault. The
  load-bearing sentence: **"By default a base includes every file in the vault. There is no `from`
  or `source` like in SQL or Dataview."** Views `table | cards | list | map | kanban`, summaries
  include `Unique`, `Median`, `Stddev`. A base cell edit writes back to frontmatter.
- **Two official agent surfaces, both new.** `obsidianmd/obsidian-skills` (created **2026-01-02**,
  **53,555★**, MIT, 7 skills) lists OpenCode among the agents it teaches. The CLI exposes ~120 verbs
  (`search:context` returns grep-style `path:line: text`, plus `backlinks`, `orphans`, `deadends`,
  `base:query`, `history:restore`). **There is no `obsidianmd/obsidian-mcp`** — the official surface
  is skills + CLI + Headless. Headless (`ob`, open beta, needs a Sync subscription) states the agent
  case verbatim: "Give agentic tools access to a vault without access to your full computer."

## What the field bolted on, which tells you what is missing

- **`tobi/qmd` 31,480★** — the retrieval layer practitioners add: BM25 + vector + **HyDE query
  expansion** + **RRF** + **LLM reranker**, local GGUF, SQLite, MCP tools. Its pitch for the
  `context add` tree: "allows LLMs to make much better contextual choices".
- **`logancyang/obsidian-copilot` 8,034★** — the note app hosting the coding agent.
- **`blacksmithgu/obsidian-dataview` 9,448★** — the query language that proved the need; first-party
  Bases answered it five years later (last push 2025-11-17, 672 open issues).
- **`brianpetro/obsidian-smart-connections` 5,568★** — embedding-based related notes.
- Community MCP servers: `mcp-obsidian` 4,550★, `obsidian-local-rest-api` 3,186★, `obsidian-mcp`
  752★, `obsidian-mcp-server` 716★. **10,791 plugins** listed.
- Lineage before the app: Cline's **Memory Bank** (`projectbrief.md`, `systemPatterns.md`, a
  read → verify → execute → update cycle) and Claude Code's **CLAUDE.md / AGENTS.md** auto-memory —
  the same pattern with the note app removed. Our journals are this pattern.

### Two vault systems that are near-exact analogues of Strata

**`eugeniughelbur/obsidian-second-brain`** (5,445★, 2026-03-24, MIT; "a vault that rewrites
itself"). Its `references/ai-first-rules.md` is the best single spec for what a memory note must
contain: frontmatter `date / type / tags / ai-first: true`, a mandatory **`## For future agent`**
preamble ("the next compatible agent reads this to decide relevance in 10 seconds before parsing the
rest"), recency markers per claim (`… (as of 2026-04, mem0.ai/blog/series-a)`), verbatim source URLs,
mandatory wikilinks, and **rule 7 confidence: `stated | high | medium | speculation`**. Because
wikilinks are untyped, it bolts typed edges on in frontmatter with an inverse table —
`supersedes|superseded_by, depends_on|required_by, caused|caused_by, decided_by|decides, relates_to,
contradicts` — the same move our `links` table (about/contradicts/supports) and `supersede_id` make.

Its `freshness-policy.md` is one rule enforced by a linter: **"every stored fact must be timeless,
dated, or a pointer"**; the illegal form is the undated present-tense claim; five lint rules
(FRESH-1 error on an unstamped quantitative claim, FRESH-2 warn on a stamp older than its window,
FRESH-3 the pointer target must resolve, FRESH-4 dated containers are immutable history, FRESH-5
unused suppression). Its runtime is our tier ladder in markdown: `CRITICAL_FACTS.md` "loads your
identity in ~120 tokens" (a cartridge), a **bounded-recall hook** injecting "max 4 notes, ~900 chars
— or **nothing at all** when confidence is low (abstention beats noise)", logged per decision (a
tier-3 block with abstention), a PostCompact agent that "only adds and updates — it never deletes or
merges", and four scheduled agents including `nightly` = "close day + reconcile + synthesize + heal
orphans" (our sweep). Its untrusted-words rule is ours verbatim.

**`breferrari/obsidian-mind`** (5,560★, 2026-02-28) is the hook-and-budget engineering: "Procedural
code owns the environment. The agent owns content." Five hooks; over the ceiling "the cheapest-to-lose
sections degrade to pointers — and **the meter names every one it dropped, because a silent loss is
worse than the bloat**"; folder listing collapses past a note-count threshold "so a vault can't
outgrow the ceiling through whichever folder nobody thought to configure". Doctrine for us:
**"Folders group by purpose. Links group by meaning… A note without links is a bug."** It documents
cross-agent truncation it observed: Codex "stops reading past ~32 KiB, silently"; Antigravity
"~24,000 bytes, silently".

## What the model gets right, and what it gets wrong

**Right.** (1) The file is the identity, the index disposable — the journal law's claim, in
product form. (2) Human curation is free: properties view, backlinks pane, graph view, and a base you
edit in place. Today our 3,819 facts are editable through JSON, SQL, or the memory page. (3) One
format serves agent, human, and viewer, and it is a **published, versioned** spec (obsidian-skills)
rather than a habit. (4) A cheap structured-query layer arrived in Bases. (5) Canvas and Bases YAML
are open formats other tools re-read.

**Wrong, each against a Strata column it lacks.** (1) Links are untyped and nothing traverses the
bolted-on `relations:` block. (2) No ranking: retrieval quality comes from an external index with its
own staleness story (`qmd embed` after bulk edits). (3) No scoring or provenance model — no `rel`,
no `confidence`, no `hits`, no `when` to the minute; `file.mtime` says *file touched*, not *fact
said*, which is why OKM exists. (4) No consolidation in the product: the merge/fold/supersede work is
all third-party. (5) Concurrency is text merge — Sync uses Google's diff-match-patch on markdown and
"last modified wins" on canvases, with a device-specific conflict-file option since 1.9.7; no
transactions, no CRDT, no per-field merge. (6) Name-keyed links collide. (7) Ecosystem decay (Dataview:
672 open issues). (8) Sync is $4–8/user/mo with a 5 MB per-file cap and 1 month of history on
Standard, and Headless needs a subscription.

## Measured on this box: what our own exporter already emits

`~/.config/opencode/skills/graphify` is the live skill (0.9.114, 50,367 B — not the
`opencode-custom/skills` folder); the generator is `graphify/export.py` (1,536 lines), also vendored
in `terminal/.venv`. Ran:

```
graphify export obsidian --graph ~/Projects/monitor-fw/graphify-out/graph.json --dir /tmp/opencode/obsidian-probe
→ Obsidian vault: 212916 notes   ·   Canvas: graph.canvas (44,658,369 B)
```

Composition: **183,610 node notes + 29,306 `_COMMUNITY_*.md` = 212,916 files, 91.0 MB of text,
888 MB on disk** — the gap is one 4 KiB block per file. **Flat directory, no subfolders.**

Node note, verbatim:

```markdown
---
source_file: ""
type: "concept"
community: "Community 97"
tags:
  - graphify/concept
  - graphify/EXTRACTED
  - community/Community_97
---

# unittest

## Connections
- [[_read()]] - `calls` [EXTRACTED]
- [[test_background_wire.py]] - `imports` [EXTRACTED]
```

The relation and the confidence ride **as text in the bullet**, not as an edge type — so Obsidian's
graph view colors by node tag and cannot show them. Frontmatter is exactly `source_file / type /
community / tags[]` (+ `location:` when present), all scalars escaped by `_yaml_str` "so a hostile
source_file or community label cannot break out and inject sibling keys". Naming is defended
end-to-end: dot-prefixes become `dot-`, `\ / * ? : " < > | # ^ [ ]` are stripped, a trailing `.md`
is dropped, and `_dedup_node_filenames` appends `_1…_9999` on the **lowercased** stem for
case-insensitive filesystems. Community notes emit a **Dataview** live query — the exporter is
Dataview-era, not Bases-era.

Ownership is a **manifest** (`.graphify_obsidian_manifest.json`): `_owned_write` refuses to overwrite
a file graphify did not create, skips byte-identical writes ("rewriting an unchanged note churns
disk and fires inotify / re-index / sync for nothing"), and prunes notes for nodes that left the
graph. That is a ready-made answer to the source-of-truth question: **the exporter owns its notes,
the human owns the rest.** Cheaper sibling: `export wiki` = `index.md` + one article per community
and per god node — ~1/80th the files.

**And we already ship the Obsidian interaction, with the two things Obsidian lacks.** The Graph tab's
node inspector (2026-11-16, the owner's Obsidian ask): "a node is a note, its connections are links,
and clicking a link walks the vault. The body is the store's LIVE data… Relation chips and
confidence tags ride every link, so a walk shows its own evidence." The graph is not only a picture:
it casts a third vote in the fusion (`memory.py:1257`), and live hits carry `graph_rank` beside
`lex_rank` and `cos_rank`.

## What a Strata vault export would be

Mapping: `shelf → folder` (86 folders), `fact row → <slug(id)>.md`, `text → body`,
`when / filed / confidence / hits / scope / derived → frontmatter scalars`,
`supersede_id → supersedes / superseded_by` wikilinks, `links → relations: {about, contradicts,
supports}`, `why → ## Why`, `provenance → ## Source`. Doc chunk rows → one note per book with chunks
as `^block-id` anchors (the corpus is already files: `founding_corpus/`, 140 files, 114 MB).

**Buys:** human browseability of the facts with the graph pane we already imitate; **Bases as a live
ledger** — ~20 lines of YAML for "facts on shelf TECH, not superseded, sorted by `confidence` DESC,
grouped by `shelf`, with a `Unique` summary", editable in place; greppability of facts, not just
journals; portability into the 8+ agents that read obsidian-skills; a third reader for the persona
cartridge, whose six files are already a hand-curated vault with cross-references.

**Costs:** a second source of truth needing a stated direction (one-way is honest; bidirectional
means parsing frontmatter back into `UPDATE`s while the harvest — gated on 240 s of engine silence,
median said→written 6.92 h — is also writing); ranking loss on the browse path (no `rel`, no fusion,
no graph vote in a vault search); file cost (facts alone ≈ 2,106 notes ≈ 8.6 MB; all 33,475 chunks
≈ 137 MB of block overhead plus re-index churn); sync licensing and diff-match-patch collisions;
conventions nothing enforces — which is exactly why OKM ships a linter.

**The cheapest version worth building**, three steps, no plugin, no sync:
1. `tools/m10_vault.py --out ~/vaults/strata` — fact notes in shelf folders, frontmatter as above,
   links as `relations:` plus a `## Connections` bullet so the graph view draws them. Reuse
   graphify's manifest / `_owned_write` / prune semantics: proven, byte-stable, idempotent.
2. Two `.base` files — the ledger (shelf × confidence × hits, `limit` 50) and the supersession chain
   (`relations.supersedes` non-empty) — plus a Bases-flavored `Home.md`, replacing the Dataview block.
3. A **lint, not a schema**: fail on a fact note with no `when`, no `shelf`, or a `supersedes:`
   pointing at a missing file. The field converged: "a linter that fails the build beats a field."

Retrieval stays in Postgres. The vault is a human-shaped projection of standing text — what the
cartridge is to the K/V cache.

## Unverified

- The second-brain project's bi-temporality claim ("track when it was true AND when the vault learned
  it") is README-level; its field-level implementation was not read.
- Practitioner performance claims (QMD speed, retrieval quality) are self-reported, unmeasured here.
- Star counts move daily; they are an adoption proxy, not a quality measurement.
