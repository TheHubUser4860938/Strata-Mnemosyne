# Hindsight (vectorize-io) — the four-network memory, read in code

**Read 2026-11-23**, README + paper + docs, then the repo at HEAD (cloned, code read).
https://github.com/vectorize-io/hindsight — Python, **MIT**, no CLA, **~62,900 stars**, 7,401 forks,
221 open issues, created 2025-10-30, pushed the day of this read, **78 releases** (cadence weekly →
several a week: v1.0.0 2026-10-13, v1.2.0 2026-11-03, v1.2.3 2026-11-19), ~291 contributors, ~6,115
tracked paths. Paper **arXiv:2512.12818** ("Hindsight is 20/20: Building Agent Memory that Retains,
Recalls, and Reflects", Latimer, Boschi, Neeser, Bartholomew, Srivastava, Wang, Ramakrishnan —
Vectorize + Virginia Tech + The Washington Post, CC-BY 4.0, 2025-12-14).

The largest of the ten systems in this directory by adoption, the closest to ours in storage, and
the furthest in surface area. The real code is `hindsight-api-slim/hindsight_api/` (the PyPI
`hindsight-api` is a metapackage on `hindsight-api-slim[all]==1.2.3`); `memory_engine.py` alone is
1.29 MB, `retain/orchestrator.py` 260 KB, `reflect/prompts.py` 100 KB.

**Its frame** (abstract): current systems "blur the line between evidence and inference, struggle to
organize information over long horizons, and offer limited support for agents that must explain
their reasoning."

---

## A. The data model — three shipped layers, and the fourth is gone

Postgres tables: `banks`, `documents`, `chunks`, `memory_units`, `entities`, `unit_entities`,
`entity_cooccurrences`, `memory_links`, `invalidated_memory_units`, `mental_models`,
`mental_model_history`, `observation_history`, `async_operations`, `llm_requests`, `audit_log`,
`webhooks`, `attachments`, `directives`, `learnings`, `graph_maintenance_queue`,
`entity_maintenance_queue`, plus a knowledge-bank family. ~120 migrations with merged heads.

`memory_units` (`models.py:132-204`) is the fact row:

```
text, embedding vector(384), context,
occurred_start, occurred_end, mentioned_at, event_date (legacy),
fact_type IN ('world','experience','observation'),
tags VARCHAR[], metadata JSONB, document_id, chunk_id,
consolidated_at, consolidation_failed_at, edited_at,
proof_count, source_memory_ids uuid[], observation_scopes JSONB,
search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text || ' ' || context)) STORED
```

| layer | what it holds | Strata's nearest |
|---|---|---|
| **world** | objective facts — *including the user's preferences, rules and corrections* | a `fact` lane row; our `USR` shelf is the preferences half |
| **experience** | the agent's own first-person actions ("I touched the stove and it hurt") | the assistant's narration, harvested into the same row type — we have no row type of its own |
| **observation** | the consolidated belief layer: deduplicated, `proof_count` + `source_memory_ids`, refined in place | **none** — `proof_weight 0.15` counts proofs at read; no belief row |
| **mental model / page** | a standing answer to a question you define once, rewritten in the background, **read as a database read** | the **tier-2 cartridge** and the six persona files — same idea, hand-written |

**Correction to the paper, from the migrations:** the fourth network (the opinion layer) is gone —
`g2h3i4j5k6l7_remove_opinion_fact_type.py` sets the CHECK to the three above and
`DROP COLUMN IF EXISTS confidence_score`. **The shipped schema has no confidence field.** We have one,
and it feeds the ranking. Naming churn to expect: one migration (2026-01-26) renames the
`mental_model` fact_type → `observation` **and** the `reflections` table → `mental_models`. Two
concepts, three names, in one revision.

**Edges.** `memory_links(from_unit_id, to_unit_id, link_type, entity_id, weight, bank_id)` with
`link_type IN ('temporal','semantic','entity','causes','caused_by','enables','prevents')`,
`weight ∈ [0,1]`, a partial index on `weight >= 0.1`. Seven kinds against our three
(`about`/`contradicts`/`supports`) — and a code comment is the honest version of the causal story:
*"Retain writes `caused_by` only. Keep the historical causal values valid so existing rows and
transfer archives remain queryable."* The "graph" is **relational** — adjacency tables plus recursive
CTEs — not a graph DB, so there is no second database to operate.

**Provenance is kept, not replaced.** Every fact carries `document_id` + `chunk_id`; `chunks.chunk_text`
and `documents.original_text` are stored by default, so a fact is a *projection over retained source
text*. Attachments ride the fact they were drawn from: *"an attachment shown next to a memory means
the model looked at it to produce that memory — it is evidence, not decoration."* Recall returns a
`source_facts` map with a `source_facts_truncated` flag (`response_models.py:624-675`).

**Supersession is not a chain.** Consolidation rewrites the observation's text **in place** and keeps
the old value as a bracketed annotation the prompt defines verbatim — *"A bracket after it,
`(YYYY-MM-DD HH:MM: …)`, is an earlier state that the text before it replaced"*
(`consolidation/prompts.py:33`) — capped at **3** earlier states (`consolidator.py:1488`), with full
snapshots in `observation_history` (cap 50, split out of a JSONB column because *"the old
single-JSONB-column design hit Postgres's hard 256MB jsonb limit → SQLSTATE 54000 and stuck rows"*).
Deleted facts go to `invalidated_memory_units` — `LIKE memory_units INCLUDING DEFAULTS`, with
`invalidation_reason`, no indexes, no embedding (a revert recomputes it). Cold storage, no cost.

**Salience.** `proof_count` (distinct evidence), `entities.mention_count`,
`entity_cooccurrences.cooccurrence_count`, recency from `created_at`. Our `hits` counts times
**served**; theirs counts facts **behind** a belief. Two different theories of importance.

**Bank** = the isolation unit: `disposition JSONB '{"skepticism":3,"literalism":3,"empathy":3}'`,
`mission`, `background`, `kind 'memory'|'knowledge'`, per-bank config. Isolation is strict, "no
cross-bank leakage". Our `scope` is the same partition without the disposition.

## B. Write path — one LLM call per 3,000 chars, then everything deterministic

`retain(bank_id, content, context, timestamp, document_id, tags, observation_scopes, metadata)`,
async on a worker or sync.

1. **Deterministic chunking** at `DEFAULT_RETAIN_CHUNK_SIZE = 3000` chars, sentence-aware with a
   separator ladder, plus conversation-turn, JSONL and image-aware chunkers
   (`retain/fact_extraction.py:574-954`). An image is charged 1,500 chars — deliberately under a real
   image's cost so prose shares the chunk.
2. **One LLM call per chunk** (`_extract_facts_from_chunk`, `fact_extraction.py:2217`), a typed
   response with an `accept_reply` guard and an auto-split retry. That one call returns facts **and**
   entities **and** temporal ranges **and** causal relations. Modes: `concise`, `verbose`, `custom`,
   `verbatim`, and `chunks` — **`chunks` costs zero LLM calls**.
   The vendor's own yield estimate (`config.py:2071`): *"Each chunk produces ~17 facts, so 100 chunks
   = ~1700 facts/batch"* — ~17 facts per 3,000 chars, against the paper's *"2–5 comprehensive facts
   per conversation"*.
3. **No LLM at all** for entity resolution (`memories/pg/entity_resolver.py`: spaCy extraction,
   `pg_trgm` GIN candidate lookup, union-find in-batch clustering that keeps the most-mentioned name
   as canonical; `intrabatch_merge_similarity=0.5`, `merge_min_similarity=0.3`, `max_candidates=200`
   because *"every candidate costs synchronous string comparison on the event-loop thread"*), for
   embeddings (default local `BAAI/bge-small-en-v1.5`, 384-d), and for link building.
4. **Temporal links are a sorted sliding window**, `weight = max(0.3, 1.0 − Δhours/window)`,
   bidirectional, capped per unit (`links.py:142`) — linear with a floor, not the paper's
   `exp(−Δt/σ)` (Eq. 4). **Semantic links are a kNN graph materialized at insert time.**
5. **Delta retain:** per-chunk `content_hash`, so re-upserting a document re-extracts only changed
   chunks — and the stored hashes are prefetched *as a task*, not awaited, so chunking overlaps the
   read: *"Started, not awaited… on a store whose cost is round trips, this read is a whole one on
   the critical path of every retain."*
6. **Then background consolidation**: optional decision-model triage (1 request/fact), 1 LLM call per
   **8 facts** per tag scope, plus 1 dedup adjudication per create/update at cosine ≥ 0.97.

Entities are canonicalized by a unique index `ON entities (bank_id, LOWER(canonical_name))`;
`key:value` labels become entities of `entity_kind='label'` that never fuzzy-merge.

## C. Read path — four arms, zero LLM calls, three multiplicative boosts

| arm | implementation (`engine/search/retrieval.py`, SQL in `memories/pg/recall.py`, `link_expansion.py`) |
|---|---|
| **semantic** | pgvector HNSW cosine with a **partial index per fact_type** (`idx_mu_emb_world`, …), `LIMIT recall_budget`, `hnsw.ef_search` sized to match |
| **keyword** | five pluggable BM25 backends; the default `native` is `tsvector` + `ts_rank_cd`, documented honestly as **"(TF-IDF, not true BM25)"** — our lexical arm is true BM25 with family-scoped idf, and it beats theirs on the definition |
| **graph** | one CTE, three signals: entity self-join `COUNT(DISTINCT entity_id)` with a LATERAL per-entity cap of 200 *"to prevent high-fanout entities from exploding the self-join"*; the precomputed semantic kNN checked **both directions** ("the graph is not symmetric"); causal links scored `weight + 1.0` ("highest-quality signal"). Additive: `tanh(shared_entities*0.5) + knn_weight + (causal_weight+1.0) ∈ [0,3]`. On timeout it drops entity expansion |
| **temporal** | parsed window → entry points spread round-robin over **8 equal time buckets** (`_TEMPORAL_COVERAGE_BUCKETS`) → bounded BFS over temporal+causal links, with *"a safety cap on BFS iterations to prevent runaway spreading in dense graphs"* |

Then **fusion → rerank → boost → pack**:

- **RRF at k=60, arms weighted equally** (`search/fusion.py`). We ship k=1 — the constant Graphiti
  and Zep converged on, which we swept to 1 on our own store (top1 0.517 vs 0.504 at k=60, +0.004
  block coverage at the width a real block shows). Neither number is portable; both were measured.
- **A second shipped fusion mode is the more interesting artifact**: `interleave_fusion`, round-robin,
  added because *"the near-identical existing observation (the 'twin' to merge into) is semantic rank
  #1, yet shares no source-fact graph link and little lexical overlap, so RRF drops it below the
  recall budget cutoff and the LLM never sees it → creates a duplicate."*
- **Cross-encoder rerank**, prefiltered to the top 300 by RRF, sigmoid-normalized. Default provider
  `local`, model `hindsight-ai/hs-rerank-1` (114M, MIT) — **reranking is free of LLM billing by
  default**. A decision model can replace the reranker with typed relevance judgments (+ `prune`,
  `dedup`).
- **Multiplicative boosts**: `final = CE × recency × temporal × proof`, `boost = 1 + α(signal − 0.5)`,
  α = **0.2 / 0.2 / 0.1**; recency `clamp(1 − days/365, 0.1, 1.0)`; proof
  `clamp(0.5 + ln(proof_count)/10, 0, 1)` (max +5%). Rationale in code: additive boosts *"would give
  the same absolute bonus to every candidate regardless of relevance"*. (The recency α became a config
  knob the day of this read.)
- **Token packing** (`engine/fact_budget.py`): spend in rank order; an oversized fact **skips itself,
  it does not evict the tail**; and a floor — *"when no fact fits at all, the top-ranked one is
  returned whole and over budget, because the alternatives are worse: an empty answer reads as 'this
  bank knows nothing about that', and a fact clipped mid-sentence would be a claim the memory never
  made."*

**Budget:** `budget` low/mid/high = 100 / 300 / 1000 candidates, or adaptive at 2.5% / 7.5% / 25% of
`max_tokens`, clamped [20, 2000]; `max_tokens` default 4,096, and *"Only the memory text counts
toward the budget — metadata is free."*

**A recall returns**: `results[]` (text, fact_type, context, `occurred_start/end`, `activation`, tags,
document_id, chunk_id, metadata, attachments) plus optional `entities` (canonical entity state),
`chunks` (the verbatim source that produced each fact), `source_facts` + `source_facts_truncated`,
`documents` (knowledge-bank passages, documented as **authoritative**: *"when a document and a memory
disagree, the document wins"*), and `trace`.

**LLM calls per recall: zero** by default — one embedding call plus a local cross-encoder. Query
analysis is deterministic (`DateparserQueryAnalyzer` / `TransformerQueryAnalyzer`). **Multi-hop:**
the temporal arm iterates (bounded BFS); the link-expansion arm is seeds → one expansion step, with
depth supplied by insert-time kNN links. The docs' "Alice → manager → team → projects at high budget"
overstates the graph arm.

## D. Consolidation — the rung we do not have, and the prompt is the design

Two things carry the name. **Consolidation** = facts → observations, background, on by default
(`DEFAULT_ENABLE_AUTO_CONSOLIDATION = True`, `DEFAULT_CONSOLIDATION_USE_DECISION_MODEL = True`).
**Reflect** = the answer-generating agent.

Mechanics: `consolidation_batch_size=50`, `max_memories_per_round=100` (*"Limits how long one bank
holds a worker slot"*), `llm_batch_size=8` facts per call, parallelism 4 over tag scopes, 3 outer
attempts. *"Each scope is consolidated in its own LLM call, so one scope's mission never reaches
another scope's call."*

**The prompt carries a closed verdict vocabulary per fact** (`consolidation/prompts.py`):
`kind ∈ momentary | lasting` ("momentary" = greetings, thanks, what is on a screen — *"This is about
TIME only, never about who or what the fact names"*), and per candidate observation
`effect ∈ unrelated | repeats | changes | ends`, with the traps written in: *"a name a letter or a
word apart — 'ledger-sync' / 'ledger-sink', 'Paolo' / 'Paola' — is a DIFFERENT subject"*; *"A count is
changed only by a fact that states the new number itself: one member arriving, leaving or dying
('adopted a puppy', 'Shadow died') is NOT a new count."* Shape law: *"One short sentence about ONE
subject and ONE facet… never join facets into one sentence, never add a new facet to an existing
observation."* `changes` keeps the old value as prose history; `ends` rewrites group membership
"then who left", everything else "the past tense with the date"; shown-wrong → *"say it was wrong and
what is true"*. `deletes` are rare and exact, with `merged_into`: *"Never delete because something
changed or ended."*

**The highest-leverage idea in the file: the time comparison is done in code, not by the model.**

> *"Facts are NOT given in the order they happened: old conversations are imported late… The
> comparison is done for you: in a fact's `closest existing observations`, the ones stated after that
> fact are marked `(stated after this fact)`, and an observation stated after every new fact carries
> `"newer_than_input_facts": true`."*

The header comment records the ablation beside the design: this format replaced a create/update/delete
prompt — *"gemma-4 scored 29/40 on the consolidation evals with that one and 36-38/40 with this one,
with no code checks and no second call"*; judging every observation cost 2× the output tokens (99%
came back "unrelated"); listing only the nearest lost the traps (*"a named dog bumped the count;
37 → 30/40"*).

**Dedup:** on create *and* update, cosine ≥ **0.97** triggers a focused 1-by-1 adjudication:
*"If they assert the SAME fact (wording aside), set action to merge and provide a single observation
that preserves EVERY detail from both. If they differ in ANY important detail — a number/quantity, a
named entity or language, a negation, or a condition — set action to keep."* Postgres-only SQL
(`unnest`/`array_agg`, `UPDATE … FROM`), so the Oracle path skips it.

**Triage** (`consolidation/triage.py`) settles `restates` and `chatter` with the 0.8B decision model
before the LLM, one typed request per fact, up to 10 candidates, gated on **self-consistency** —
*"a verdict only stands when the answers agree with each other… previously Nouls and per-answer
confidence bars (0.8-0.95) decided: tuned to jev-latest, they let a hedging model such as
hindsight-decision (answers 0.3-0.7) settle nothing."* Their claim: ~40% fewer consolidation LLM
calls at the same pass rate.

**Promotion / demotion / decay.** Promotion: facts → observations → mental models/pages. Demotion:
`consolidated_at IS NULL` — the partial index `idx_memory_units_unconsolidated` **is** the work queue —
and `consolidation_failed_at`. **There is no row-level decay or forgetting**: decay lives only in the
retrieval score (recency over 365 d), and the paper lists "controlled forgetting, time-aware belief
revision" as future work.

**Mental models / pages** (`mental_models`: `subtype ∈ structural|emergent|pinned|learned`,
`structured_content JSONB`, a `history` table, cron refresh, `version`,
`last_full_refreshed_at`, `last_refresh_failed_at`, `last_refreshed_source_query`): *"You define the
question once; Hindsight writes the answer, stores it, and rewrites it in the background… Reading one
is a database read — no retrieval, no LLM call — so an agent can boot with a page of settled
knowledge."* Delta refresh asks each memory *"could this change the page?"* — *"when none can, the
update makes no LLM call at all."* And `GET /observations/tree` renders every observation as a folder
of markdown grouped by entity **with no LLM call**, rebuilt per request, in an Open Knowledge Format
so an agent can `ls` and `grep` it.

**Reflect** is an agent loop, `DEFAULT_MAX_ITERATIONS = 10`, over `search_mental_models →
read_mental_models → search_observations → recall → expand → done`, with citation validation (*"only
IDs that were actually retrieved can be cited"*) and disposition injected as prose, not numbers —
*"The numbers alone are not an instruction: a weaker model reads `skepticism=5` as metadata and
answers exactly as it would at skepticism=1 — which is what
`test_high_skepticism_response_is_more_hedged_than_low` keeps catching on gemini-2.5-flash-lite."*
With a decision model the loop flattens: one call writes the query, all layers search in parallel,
the model prunes and judges "is this enough", and only then does an LLM write.

## E. The interface

- **REST** (FastAPI, `HINDSIGHT_API_*`, hierarchical config global → tenant → bank, multi-tenancy via
  Postgres schemas). 19 client API groups.
- **MCP is first-class:** every server exposes `/mcp/{bank_id}/` with **39 memory tools + 10 knowledge
  tools** (`mcp_tools.py:_ALL_TOOLS`).
- **SDKs:** Python, TypeScript, Go, Rust, CLI, plus `hindsight-all` embedded (in-process on **pg0**,
  Vectorize's own embedded Postgres — the same trick ADR-002 bought us).
- **Zero-code path:** `hindsight-litellm`'s `wrap_openai()` / `wrap_anthropic()` — recall before every
  call, retain after, per-call `hindsight_*` overrides. The cheapest integration in the space.
- **48 integration directories** in `hindsight-integrations/`, incl. **opencode** and a coding-agents
  package that builds a per-repo bank from git history + past sessions and injects curated pages at
  session start.
- **Ops:** a separate `hindsight-worker` process, Prometheus `/metrics`, an admin CLI for migrations /
  bank repair / stuck operations, webhooks (`retain.completed`, `consolidation.completed`), and an
  `llm_requests` table so per-call cost is queryable in SQL.

## F. Real vs marketing

**Substantiated in code, line for line:** the four arms, RRF, the 300-candidate prefilter, α = 0.2/0.2/0.1,
the 100/300/1000 budget ladder, the 4,096-token default, the 0.97 dedup merge, the triage gate, the 8
temporal coverage buckets, the observation `source_memory_ids`/`proof_count` evidence model,
bi-temporal fields, the embedded-pg0 path, 25+ LLM providers. The README's technical summary matches
the source — unusually true for this field.

**Partly substantiated:**
- **"91.4% on LongMemEval."** Paper Table 3 is **LongMemEval-S, 500 questions**, judged by
  **GPT-OSS-120B at temp 0.0 — their own judge**. The fair same-backbone number is **83.6% vs 39.0%**
  full-context OSS-20B. The 91.4% row is Hindsight's memory stack on OSS-120B with **Gemini-3 Pro as
  the answer generator** — a frontier model on top. The apples-to-apples row is **89.0%** (OSS-120B).
- **"Independently reproduced by… Virginia Tech Sanghani Center and The Washington Post."** Both are
  **on the author list** (Neeser/Washington Post; Srivastava, Wang, Ramakrishnan/Virginia Tech).
  Co-author institutions, not third parties.
- Baselines are self-reported: Supermemory's row comes with Supermemory's GPT-4o judge, Hindsight's
  with GPT-OSS-120B (§7.3). LoCoMo baselines are *"as claimed on the official Backboard… results. We
  treat these numbers as reported reference points rather than our independently reproduced
  baselines"*, and Backboard's 90.00 *"could not be independently reproduced."*
- The **"#1 on every Agent Memory Benchmark"** link goes to **agentmemorybenchmark.ai, Vectorize's
  own site**; LongMemEval-S there reads **94.6%**, three points above the paper-visible number, with
  no paper behind it.
- **"Memory 2.5× cheaper and 2× faster, with better answers"**: their evals, graded by
  `gemini-3.1-flash-lite`, which the post concedes *"is also one of the seven LLMs tested, so its own
  rows are self-graded"*; cost is tokens at list price; "all of Hindsight" is *"an equal mix of the
  eval's operations… a real workload weighs them differently."*
- **"Used in production at Fortune 500 enterprises"** — UNVERIFIED, no names.
- **"Oracle AI Database with full feature parity"** — real, with a named exception (observation dedup
  is Postgres-only). The docs' "No Storage Abstraction" claim is **stale**: there is a
  `MemoriesExtension` interface (`memories/base.py` 231 KB, `postgres.py` 71 KB, `pg/` 16 modules)
  plus `ops_postgresql.py` (92 KB) / `ops_oracle.py` (70 KB).

**Not substantiated:** the paper's **four networks** (the opinion network and its confidence scores
are gone from the shipped schema); Eq. 4's `exp(−Δt/σ)` temporal weight (code: `max(0.3, 1 − Δh/W)`);
*"2–5 comprehensive facts per conversation"* against the config's ~17 facts per 3,000-char chunk; and
paper §7.3, verbatim: *"Token budgets for retrieval are set to **<add>** tokens for LongMemEval and
**<add>** tokens for LoCoMo"* — **unfilled placeholders in the published paper, on a variable that
directly moves the score.**

**Known weaknesses, from the 221 open issues** (the quality-relevant ones): #2551 (13 comments)
extraction context is chunk-bounded → misattribution; #2548 JSON chunking loses critical context;
#6010 knowledge pages ranked by one embedding that only sees the start of the page; #5574 delta-mode
mental models grow to 3-4× `max_tokens` — *"the budget is a prompt hint only and nothing enforces
it"*; #6600 reflect times out under load, contending with consolidation; #6241 append retains rewrite
every prior unit each turn; #5210 per-message temporal provenance collapses to the conversation
timestamp; #6818 relayed content retained as the agent's own experience; #2235 (top-reacted, +12)
coarse team/agent/memory-level access control; #4061 a standing daily security-sweep backlog.

**The strongest evidence in the repo is the eval suite, not the README.**
`hindsight-system-evals/README.md` ships ~100 judged cases across retain / recall / consolidation /
reflect / refresh-pages / knowledge, category-labelled (`test_retain[temporal/no-event-date]`), with
per-model pass rates published *and the failures explained*: `gpt-6.1-sol 35/35`;
`gemini-3.1-flash-lite 32/35` (*"obeys 'the CEO resigned' written in the content; invents a date when
none is set"*); `gemma-4-26b-a4b 27-33/35` (*"Spanish stored as English; drops 'Marco was nervous'"*),
with a trap-first grading rule and *"a single red run is a signal to re-run, not proof of a
regression."* That is our bench-panel discipline, in public, for the models they ship against.

## G. Maturity and lock-in

MIT, no CLA. Python ≥3.11. Core: FastAPI + uvicorn, **asyncpg**, SQLAlchemy 2.0 (pinned `<2.1`, with
the reason in a comment), alembic, **pgvector**, pydantic v2, fastmcp, `toktok-rs` (their tokenizer,
chosen over tiktoken), OpenTelemetry/Prometheus. The `[all]` extra pulls **torch, torchvision,
sentence-transformers, flashrank** for local embeddings and the local reranker — a heavy install for a
memory server, and why `hindsight-all-slim` exists for Intel Macs.

**Rip-out: moderate.** ~120 migrations with a rename chain means the schema is still moving; a bank
export/import API exists, the data model is legible, text is plain, embeddings are swappable 384-d.
The genuinely Hindsight-shaped things you re-derive: `observation_scopes`,
`source_memory_ids`/`proof_count`, the bracketed earlier-state convention, and a prompt set tuned to
the specific small models they run (the eval deltas in the comments are for gemma-4 and TypeSafe's
Jev). The 48 integrations all sit on the REST surface, so replacing Hindsight means rebuilding that
surface, not the store.

## H. What a competing implementation should steal, with the file that shows it

Ranked for Strata, cost stated against this box (24 GB GPU, one engine, served model at ~90 tok/s
decode):

1. **Compute the time comparison; let the model read the mark.** `consolidation/prompts.py:156-162`.
   A boolean against `mentioned_at` — for us against `when`. **Zero new models, zero new indexes**,
   and it attacks our worst slice (temporal 0.465). Cheapest item on this list.
2. **A closed verdict vocabulary, pinned by a per-category eval on the model you actually run.**
   `consolidation/prompts.py:100-150` (29/40 → 36-38/40). This is the direct answer to "the clerk's
   labeling quality is unmeasured": choose the output shape a small model gets right, then pin it.
3. **`proof_count` as a set union in SQL** — `count(DISTINCT e) FROM
   unnest(source_memory_ids || $2::uuid[])` (`memories/pg/consolidation.py:174`). Evidence strength
   that cannot double-count, on the row, with the source facts returned under a budget that reports
   its own truncation. Our `hits` counts times served; this counts facts behind a belief.
4. **Bounded inline history: one sentence, one facet, the old value as a bracketed annotation capped
   at 3**, with a deep history table beside it (`consolidation/prompts.py:112-114`,
   `consolidator.py:1488`). A scar you can read **on the returned row**, with no join per recall — our
   linear `supersede_id` chain costs a lookup to see the prior state.
5. **Pay the LLM at write time so reads are free** (`entity_resolver.py`, `link_expansion.py`,
   `docs/developer/performance.md`): 1 call/chunk, then deterministic resolution, kNN links
   **materialized at insert**, and a zero-LLM read at 100-600 ms. Our read path is already in this
   shape; the insert-time kNN links are the part we lack (our `links` are direct-only, never
   traversed).
6. **Three budgets, one per kind of text** (`engine/fact_budget.py` + `source_facts` + chunks under
   `max_chunk_tokens`), with skip-not-evict and a floor of one whole result. This is a complete answer
   to our own complaint that "the block's budget is spent on this afternoon's sentences": facts,
   evidence, and passages each get a cap, so the durable tail stops losing to the recent head.
7. **`interleave_fusion` for the near-duplicate case** (`search/fusion.py`): round-robin guarantees
   every arm's top hit a slot, because RRF averages a semantic #1 down below the cutoff. We have one
   fusion mode and a measured near-dupe problem (`m4_families.py`: 90 violating pairs, 25 families).
8. **Scope-conditioned consolidation** (`consolidator.py:_ConsolidationStrategy`,
   `docs/developer/observations.mdx`): fnmatch patterns, first match wins whole, each carrying its own
   mission, observation cap and source-fact budgets, with a **preview** endpoint that says how many
   existing scopes each rule claims. The shelf analogue is exact: a mission and a row cap per shelf
   family, and `m4_shelftidy --preview`.
9. **A small typed decision model, accepted only on self-consistency** (`consolidation/triage.py:34-39,
   215-223`): 0.8B, Apache-2.0, one request per judgment, per-option probabilities, agreement gate
   replacing tuned confidence bars. ~167 ms median against 1-7 s for an LLM call. Our clerk is the
   served model at a 1,400-token budget whose shelf moved 2 of 4 identical asks at temp 0.8.
10. **Pages and the observations tree** (`docs/developer/mental-models.mdx`, `pages.mdx`,
    `observations.mdx#observation-tree`): a standing answer read as a database read, and a
    markdown-by-entity tree with no LLM call. That is our shelf catalog plus tier-3 with a durable,
    human-browsable summary layer on top — the rung our own pain list says is missing, and the answer
    to both `always.md` (55,881 hand-kept chars) and the vault idea.

## What we have that Hindsight does not

1. **Tier-2 K/V cartridges.** Its recall returns text a client resends (its own budget default is
   4,096 tokens). Ours restores a 720 MB standing cart in ~130 ms, so ~30k standing tokens cost no
   prefill. Nothing in its 19 API groups has an equivalent.
2. **The shelf as an address.** A call number is browsable and human-legible with a subtree and a
   catalog verb; a bank is a partition, and its entity tree is a folder of markdown, not an index.
3. **True BM25 with family-scoped idf** — their default lexical arm is `ts_rank_cd`, documented as
   TF-IDF. We rejected `ts_rank_cd` on 2026-10-16 for exactly that reason (top1 0.394 → 0.186).
4. **A confidence field that ranks.** Theirs was removed; ours (0.8 default, evicted worst-first) is
   live.
5. **A row-level supersession chain** naming what it replaced, per row, forever. Theirs is 3 bracketed
   states inline plus a 50-deep snapshot table.
6. **The document index over the file**: `docs.read`/`expand` cut the passage out of the source file
   with `offset`/`sha256` provenance. Their chunks are the text of record, stored in the DB.
7. **At-rest encryption with the vectors inside**, and a restore verified byte-identical.

## Unverified

- Fortune 500 production usage (no names).
- The 94.6% LongMemEval-S number on their own benchmark site (no paper behind it).
- Practitioner latency/cost claims beyond their own docs.
- The disposition traits: shipped in the schema as JSONB, and `reflect` injects them as prose; the
  measured effect on answer quality is theirs, not mine.
