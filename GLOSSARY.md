# GLOSSARY — the domain language of Strata Mnemosyne

Names for the things the memory system is made of, with the code that owns each one.
This is a vocabulary, not a manual: [docs/MEMORY_CORE.md](docs/MEMORY_CORE.md) is the narrative,
this file is what a word means when the narrative and the code use it differently.

Two vocabularies live side by side, deliberately. These are the **domain** names (the store's own
language, grown from the Library of Congress's shelf model). The **architecture** vocabulary used
in reviews — module, interface, depth, seam, adapter, leverage, locality — is separate, and names
the shape of the code rather than the things it stores.

## The store

| term | meaning | owner |
|---|---|---|
| **row / fact** | one durable sentence the store keeps. `memories` table: text, scope, class, source, confidence, provenance (jsonb), created/updated/last_seen, hits, invalid_at, superseded_by, pinned. | `terminal/serve/memory.py` `_PG_DDL` |
| **chunk row** | a slice of a document, stored in the same table as a fact, keyed to its corpus in `provenance`. 33,475 of them (140 books) beside 3,819 facts, measured 2026-11-23. Facts and chunks are two families in one table; every ranking statistic is measured per family. | `terminal/serve/docs.py` |
| **shelf** | a call number, not a folder: `POL`, `TECH/MCP`, `MEM/CRG.3.431`. Prefix match, so `STR` pulls `STR/GEN`. A row with no shelf is **wild** and rides every unfiltered request. 91 shelves live today; 19 of them hold ≤3 rows. | `class` column, `class_name()`, `shelf_sql()` |
| **scope** | who may know: one `user` scope joined to every search, plus per-project scopes. A project fact never leaks into another project's recall. | `scope_name()` |
| **lane** | a fact's kind, carried in the shelf's subclass and in `provenance`: `fact`, `taboo` (a negative constraint, evicted last), `state:<key>` (a machine's self-report, superseded by key). | `curate_loop.py` extract grammar |
| **supersession chain** | a corrected row names what it replaced (`superseded_by`, `invalid_at`); the scar stays visible. 6,684 retired rows beside 3,819 active, measured 2026-11-23. | `invalidate()`, `correct()` |
| **link** | a typed edge between two rows: `about`, `contradicts`, `supports`. One relation per directed pair. Never traversed by the ranking, only surfaced. | `links` table, `link()`, `links_of()` |
| **purge ledger** | the record of hard deletes: hash, 200-char head, reason, actor, timestamp. The only act that erases a row leaves the content recoverable. | `purges` table, `purge()` |
| **journal / turns** | every completed exchange, raw, as the queue the harvest reads. 43,329 turns; the `injected` column records which rows the server put on screen. | `journal_turn()`, `turns` table |

## The harvest

| term | meaning | owner |
|---|---|---|
| **the clerk** | the curation loop: extract facts from journaled turns, score them, store them, mark the turn. Runs on a 30-minute timer, gated on 240 s of engine silence. | `terminal/tools/curate_loop.py` |
| **the sweep** | the systemd timer that fires the clerk, and the tick it runs. `pressure=1` or `pending>5` buys the tick; a quiet tick plans nothing. | `strata-sweep.timer`, `tools/sweep_cron.sh` |
| **derived** | a row the harvest wrote rather than a hand. 3,437 of 3,819 facts (90%) are derived, and they ride the block at `derived_weight` 0.7. | `_trust_tier()` |
| **the janitor** | the pass that clusters fact rows so a shelf's content stays one subject. | `m4_shelftidy.py`, `_dedupe_tables()` |
| **the shelf clerk** | the model that files a fact the keyword map cannot name, against the store's own shelf list. Budget is the interface: 1,400 tokens. | `m4_reshelve.py`, `clerk_class()` |
| **the catalog** | the map of shelves the model reads: `catalog:true` returns shelf marks, row counts, newest date. Labels are rows of class `MEM/CAT` in the user scope. | `m4_catalog.py`, `browse()` |

## The recall path

| term | meaning | owner |
|---|---|---|
| **tier-1** | canceled (owner's decision 2026-10-23): the recall ladder is tier-2 over tier-3, not three rungs. | docs/MEMORY_CORE.md |
| **tier-2 / the cartridge / the cart** | the standing text seeded once as a K/V prefix: the six persona files, content-hash named, rotating only when a hand edits a file. Today 720 MB, 36,522 tokens. | `cart_text()`, `strata_control/cartridges` |
| **tier-3 / the block** | the per-turn recall block, assembled from the store under a character budget, merged into the head system turn (stable) and the newest user message (fresh). | `block_for()`, `turn_block_for()`, `_render_block()` |
| **the tool arm / browse** | `memory_search` the model calls mid-thinking: `q` (word search), `catalog:true` (the map), a bare `class` (a drawer walk, newest-first, with an `offset` cursor). | `tool_result()`, `search()`, `browse()` |
| **`rel`** | the blended score riding every returned row — the search's own belief that the row answers the question. ~1 for a top pick, ~0.1 for a polite maybe. | `search()` |
| **`@SHELF:n`** | the address a shown row carries, so a later turn can name the drawer it came from. | `block_shelf_tags` |
| **the fusion** | one score from BM25 (family-scoped idf) + cosine + recency + confidence + proof + coverage, with RRF `k=1`. | `_bm25()`, `_semantic()`, `RRF_K` |
| **the router** | the shelf pick a query gets before ranking; `route_demote` decides whether a miss filters or only sinks. | `_route()`, `_router_search()` |
| **the graph arm** | a third vote: neighbours of the fused seeds, pulled from the built graph and the store's own vectors. | `_graph_expand()`, `_sim_neighbours()` |
| **the panel** | the frozen instrument a change is scored on: 12 topics, PAPER/SHELF/FILE/MRR, ≥3 repeats, rubric fixed before the run. | `bench/p1/docs_paper_eval.py`, `docs_read_eval.py` |

## The graph

| term | meaning | owner |
|---|---|---|
| **the store's graph** | the concept map built from fact text by the served model: nodes, edges, hyperedges (one case, several facts), communities (what the graph, not the clerk, thinks the shelves are). Files beside the store in `<store>/strata-graphify/`. 4,239 nodes / 3,133 edges / 1,608 communities over 1,183 facts, built 2026-11-22 in 3,187 s (1.08M tokens in, 323k out). | `terminal/strata/graphify/` |
| **graphify** | the external tree-sitter knowledge-graph tool this repo vendors as a dependency, and whose code-map habit the fork follows: one map call before grep. | `~/.venvs/graphify`, `graphify-out/` |
| **a cart** | a saved K/V prefix: `standing` (the persona), `rows` (shelved facts), `episode` (one experience). Ledger in `carts`, with state fresh → stale → re-minted, `previous_file` and `remint_count` kept. | `carts` table, `cart_register()` |

## The persona (this fork's names for its own standing texts)

| term | meaning |
|---|---|
| **Clio** | the assistant: the recall path and the working hands — the part with rules, budgets and judgement. Mnemosyne's daughter: the retriever descends from the store. |
| **Mnemosyne / Mnemo** | the store itself: shelves, journal, sweep. Passive, curated. |
| **the six standing texts** | `soul.md` (who), `agent.md` (how), `skill.md` (kit), `user.md` (the human), `always.md` (the box), `owner-voice.md` (his register). The first three are tracked in git; the last three are box-local. |
