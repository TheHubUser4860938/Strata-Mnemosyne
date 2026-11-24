# External memory systems — research journal (tier-3 optimization input)

**Why this file exists.** Tier-3 (curated recall) is the part of Strata that is proven and measured:
LongMemEval oracle accuracy **0.761** (500 questions x 3 repeats, temp 0.8, the benchmark's own checker,
muted control), reranker worth +0.040 over lexical, injection budget worth +0.000, and a residual where
**244 of 346 wrong answer lines had every gold session already present** — reasoning, not retrieval. The
user's call for this workstream: tier-3 is "the proven one", so optimize it hard, and use the six systems
below as the inspiration set rather than inventing in-house.

**Method, stated so the depth is auditable.** One research pass per system: 10+ web searches each (their
docs, their papers, third-party comparisons, issues that reveal real failure modes) plus the actual code —
`git clone --depth 1` into `/tmp/opencode/research/<name>` and read the implementation, not the README.
Every claim in a system file carries a URL or a repo file path. Anything not confirmable in code or docs
goes into that file's `## Unverified claims` section rather than into the summary.

Per-system reports live beside this file:

| system | file | focus of its comparative question |
|---|---|---|
| mem0 | `mem0.md` | LLM-driven extract + ADD/UPDATE/DELETE/NOOP consolidation; vendor benchmark claims |
| Zep | `zep.md` | bitemporal validity (`valid_at`/`invalid_at`), edge invalidation, contested numbers |
| Graphiti | `graphiti.md` | incremental graph construction, hybrid rankers, the "no LLM at query time" claim |
| Letta / MemGPT | `letta.md` | self-editing memory blocks, sleep-time compute (their analogue of our curation timer) |
| LangMem | `langmem.md` | memory typing (semantic/episodic/procedural), consolidation prompts, evaluation tooling |
| Cognee | `cognee.md` | document spine: chunk -> section -> document provenance, ontologies, ECL pipeline |

Each ends with **portable ideas**, and each idea must state its cost (LLM calls per write / per read, RAM,
index work) and **how we would measure it** on existing instruments — `tools/lme_retrieval_ab.py --offline`
(~45 s, mechanism-level), the right-fact-in-block probes (`m4_shelf_nav.py`, `m4_position.py`), or the
LongMemEval venue (~80 min, outcome-level). An idea with no measurement plan does not enter the backlog.

## The filter every idea has to pass

Strata's constraints are what makes this a comparison rather than a shopping list:

1. **No LLM call in the interactive hot path.** Curation runs on a ~30-min timer. Several systems below
   spend an LLM call per write, per read, or both — that is a cost, not a feature, on a single 24 GB GPU
   already running a quantized MoE model.
2. **No cloud dependency, no extra database.** SQLite + FTS5 + vectors in the same file, CPU-only ONNX
   embeddings. Anything needing Neo4j/FalkorDB/Neptune or a hosted API has to be translated or dropped.
3. **Deterministic where judgment was measured to be wrong.** Strata's merge laws exist because LLM-judged
   consolidation had measured false-merge rates (44% and 39%) before the laws were added. Any "let the
   model decide" proposal arrives here already carrying that burden of proof.
4. **A claim is a measurement.** Opt-in, default path byte-identical, temp 0.8/1.0 never 0, >= 3 repeats
   for pass/fail, memory muted on /v1 probes, timings read from RESPONSES not logs.

## Cross-cutting finding 1: the published numbers in this field are not comparable

Measured on: web, 2026-10-14. This is the frame that keeps the six reports honest about their own tables.

- **Mem0**: claims **94.4% on LongMemEval** and 92.5% on LoCoMo, self-reported. An independent paper
  (arXiv:2603.04814) measured **49.0%** on LongMemEval for a Mem0 pipeline with a GPT-5-mini reader.
  - https://mem0.ai/blog/ai-memory-benchmarks-in-2026 · https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026
- **Zep**: its paper (arXiv:2501.13956) reports **94.8% on DMR** (gpt-4-turbo) / 98.2% (gpt-4o-mini) and
  **63.8% / 71.2% on LongMemEval** with gpt-4o-mini / gpt-4o. The DMR number sits on 60-message
  conversations and beats MemGPT by 1.4 points; the paper itself says the results "must be
  contextualized". Zep's **84% LoCoMo claim was re-scored at 58.44%** by an outside evaluator in
  getzep/zep-papers issue #5. Zep's own blog attacks Mem0's comparison in return ("Lies, damn, lies &
  statistics").
  - https://arxiv.org/abs/2501.13956 · https://github.com/getzep/zep-papers/issues/5 · https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
- **The benchmarks themselves are audited-faulty**: a community audit found **6.4% of LoCoMo's answer key
  is wrong and its LLM judge accepts up to 63% of intentionally wrong answers**, and argues
  **LongMemEval-S "fits entirely in modern context windows, making it more of a context window test than
  a memory test"**. LoCoMo-Plus (arXiv:2602.10715) exists specifically because LoCoMo measures explicit
  factual recall rather than beyond-factual memory.
  - https://www.reddit.com/r/AIMemory/comments/1s1jlnd/serious_flaws_in_two_popular_ai_memory_benchmarks/ · https://arxiv.org/html/2602.10715v1
- **Where the honest comparisons land**: one September 2026 survey concludes "there is no longer a
  meaningful accuracy gap to break the tie" between the leading frameworks; another puts Zep+Graphiti at
  71.2% vs Mem0's 49% on LongMemEval — a 22-point gap between two claims about the same benchmark. The
  axis that IS moving in the vendor material is **cost**: tokens per retrieval call (~6,956 on LoCoMo for
  Mem0's 2026 algorithm) and latency vs full-context (median 9.87 s, p95 17.12 s).
  - https://mnemoverse.com/docs/library/ai-memory-solutions-2026-q3 · https://mem0.ai/blog/state-of-ai-agent-memory-2026 · https://zensation.ai/en/vergleich/agent-memory-frameworks

**What Strata should do with this.** (a) Never print 0.761 beside a vendor's 94.4% without the sentence
"sames-store, same-boot, same-judge A/B is the only comparison in this project that means anything" —
which is precisely the arm-B -> arm-C discipline (+0.040 measured inside one process, one store, one
vector set). (b) The "LongMemEval is a context-window test" critique is the argument for the **queued
S-split run (200 sessions/question)**: the benchmark that gates beta-1 cannot see the failure mode that
threatens the product, which is a growing store. The S-split is the out-of-sample check on our own scaling
law, not a bonus experiment. (c) Cost numbers (tokens per retrieval, latency vs full-context) are a
language these systems use and users understand; Strata has the equivalents measured (block 15.2k chars at
96/24k, ~2.3 s first turn, 52 ms lexical / 137 ms hybrid recall at 2,521 rows) and should state them the
same way instead of only stating accuracy.

## Cross-cutting finding 2: what the six systems have in common that Strata does not

Confirmed against code in all six reports, not inferred from READMEs:

- **An LLM call at write time.** mem0 (until v3 deleted it, leaving MD5 dedup — see finding 4), Zep and
  Graphiti (entity/fact extraction plus LLM-judged invalidation), Cognee (**23–24.6x corpus tokens and 2
  LLM calls per chunk**), Letta (the model edits its own memory), LangMem (extract + consolidate). Strata
  spends its LLM budget on a 30-minute curation sweep and keeps the write path model-free.
- **Validity as a pair of dates on every fact.** Zep/Graphiti carry `valid_at`/`invalid_at` (event time)
  beside `created_at`/`expired_at` (transaction time) and expose both as query predicates
  (`edges.py:271-289`, `search_filters.py:27-52`). Strata has only transaction time: `invalid_at is null`
  is hardcoded into recall (`serve/memory.py:654`), so "was this true on 14 March?" cannot be asked.
- **A subject/entity level above the fact.** Graphiti (entity nodes + communities), Zep (the same, in
  Graphiti), mem0 (a subject-shaped retrieval signal with an explicit hub penalty, `main.py:1807-1821`),
  Cognee (a graph over chunks). Strata's facts are flat: the `df<=3` subject is computed at write time
  for the merge veto and then **thrown away at read**.
- **A document spine with provenance.** Cognee keeps `doc_id` + chunk ordinal and enforces a **byte-exact
  tiling invariant** (concatenating chunks in order must equal the source, checked on read and after every
  plan, `incremental_chunking.py:53-66`). Strata stores verbatim sentences with `{file, n}` provenance but
  no document object, no offsets, no reassembly.
- **Typed memories** (semantic / episodic / procedural — LangMem, mem0's Platform) versus Strata's single
  fact row plus a `source` trust axis (`ingest-*` vs curation vs journal), which is the closest analogue
  and the one worth keeping.
- **Placement as an operation.** Letta's core-vs-deferred-vs-skills tiers carry a per-unit `description`
  telling the reader what the unit is FOR, and moving a fact between tiers is a first-class edit. Strata's
  96-note block is one undifferentiated budget with no purpose strings — which is the most plausible
  explanation for our own measured null result on budget size.
- **Query-side routing.** Cognee ships a rule-based no-LLM query router with an explicit safety rule
  ("never add an LLM call without an unambiguous signal", `query_router.py`). Strata has document->shelf
  classification and zero query-side routing — and today measured that routing into shelves does not pay
  at 2,655 rows (see the killed list).

## Cross-cutting finding 3: what Strata has that the six do not

Also confirmed in code, so it can be stated without hedging:

- At-rest encryption with the vectors **inside** the encrypted file; a single-file store with no external
  database (all six need Postgres/Neo4j/FalkorDB/Redis or a hosted API).
- A **deterministic merge law** where cosine only proposes. Zep's invalidation is date arithmetic but the
  *candidate choice* is LLM-judged, and the result is audited bad upstream: 41% of a 3,950-fact graph
  carries `invalid_at` with **3 of 4 audited wrong** (Graphiti #1728, independently reproduced at
  16.1-49.2%). Strata's laws exist because LLM-judged consolidation measured 44% and 39% false merges.
- **Server-side agentic recall** the model can call without any client wiring, plus a UI over the same
  store. Every one of the six makes the harness do the integration.
- **Tier-2 KV cartridges**: restoring engine state (~80 ms for 247 MB) instead of re-sending text. Nothing
  in the six has an equivalent; they all pay tokens per read (mem0 publishes ~6,956 tokens per retrieval
  call on LoCoMo).
- **A measurement protocol the vendor numbers mostly cannot be checked against**: temp 0.8/1.0 never 0,
  >= 3 repeats for pass/fail, one fresh conversation per ask, the benchmark's own checker prompt verbatim,
  a muted control that answered `idk` 1,478/1,500 times, and same-store/same-boot A/B attribution.
  Cognee publishes **no LongMemEval score at all** (BEAM 0.79 is 20 questions, one conversation,
  in-sample at 10M); Graphiti's only self-hosted reproduction gives recall 37.0% and 3.65 s per turn of
  ingest against our measured 2.8 ms for a guarded write.

## Cross-cutting finding 4: the cautionary tale that validates the hard parts of our design

mem0's v3 algorithm (April 2026) **deleted** the paper's ADD/UPDATE/DELETE/NOOP step: OSS `add()` is now
single-pass ADD-only with MD5 hash dedup as its only guard (`main.py:1022`, the update prompt is dead
code), and OSS scoring has **no recency, no confidence, no state** (`utils/scoring.py:60-118`).
Consequence, in their own tracker: stale facts are an open production bug (#4956, 4 closed community PRs),
TOCTOU duplicates (#5867, #6515), and a 32-day audit reporting **97.8% junk** in one deployment (#4573).
Consolidation, decay, temporal ranking and graph memory all moved to the closed Platform. Their docs
concede full-context beats Mem0 on LoCoMo (72.90 vs 68.44). Independently: Letta's self-editing
consolidation shows double-digit drawdowns and collapses **.812 -> .375 under 20% corruption**
(arXiv:2605.12978), whose recommendation is literally "treat raw episodes as first-class evidence and gate
consolidation explicitly" — which is what Strata's journal + law + timer architecture already is.

**So the two things this project was tempted to drop — the deterministic merge law and the model-free hot
path — are the two the field's most-starred system abandoned and the second-most-starred is measured
failing on.** That is worth writing down before the next "let the model decide" proposal arrives.

## Killed today by measurement, before any of it got built

The filter these had to pass is the same one the shelf experiment failed, so they go on the record as
killed-at-this-size rather than forgotten:

| idea | where it came from | what killed it |
|---|---|---|
| two-stage retrieval (cheap pass -> infer shelf -> re-search inside) | our own LCC design | oracle navigation scores **exactly equal** to the unfiltered baseline at all three sizes; the router is **net negative** (0.888 vs 0.919) |
| "more prenamed shelves" (denser cutters) | user proposal + Graphiti subclasses | 45 clusters all smaller than the block lift the oracle by 3 probes of 197 |
| a bigger injection block **on personal-fact rows** | arm C, then the dev-store probes | at the note-bound dev budget: +0.000 relevant facts at both query shapes and both arms. **The venue half of this row is no longer killed** — re-measured 2026-10-15 with `tools/m4_blockcov.py` after the stale-pin-cache bug was found: 192/48k shows 19-20 notes against 14-16 at 96/24k and raises gold-row coverage +0.019 hybrid / +0.047 lexical. Separating it from the reranker at the accuracy level is arm C1, back on the venue queue. |
| near-dupe guard fix as a retrieval win | Graphiti #1956 | the product cost is **0.21 slots per block (0.2%)**; the cap explains 0 of 90 violating pairs |
| rank-order work as an accuracy lever | the reranker's +0.139 rank-1 swing | measured twice, and the product path is the one that counts: `tools/lme_posrank.py` on the 1,500 filed arm-C lines shows **no monotone position effect** (rank 1 0.748 vs rank 2 0.835 vs rank 10 0.833; flat inside the easy types), and `k=1`'s +0.013 top1 moves block coverage by only +0.004 -> ~+0.003 accuracy. The synthetic `m4_position.py` pilot DID find ~19 points front-to-tail, but only in blocks with exactly one answer-bearing row — real for reader attention, not for the product. The agentic tool is where rank order pays. |
| speaker/assistant-echo demotion | the knowledge-update -0.139 | parked; still parked — `k=1` does not repair it either, and the positional probe is the test of whether order can pay at all. `tools/m4_consensus.py` then showed all 11 flips were the cosine arm's OWN rank-1 row, and that a lexical-weighted fusion recovers knowledge-update (0.486 → 0.611) only by paying overall top1 (0.517 → 0.506) and top3 (0.849 → 0.830) — a metric swap, so it does not ship. |
| **the subject / entity axis** — gather by subject instead of filtering by category, the strongest idea shared by two of the six systems | Graphiti's entity rollup + mem0's hub-penalised subject index (`main.py:1807-1821`) | `tools/m4_subject.py` on the venue copy: coverage at the block's own width (k=16) 0.936 → 0.933 (lenient) or unchanged (strict), and **only 4 of 470 questions moved at all**. The headroom was real (multi-session 0.893, temporal 0.920) and the gather did not touch it — below ~11k rows the fusion already surfaces what an entity index would go and get. |

## The seventh system: LCC, the one our own taxonomy is named after (2026-10-15)

Six external systems were studied to inform tier-3; the seventh was hiding in our own design vocabulary.
`lcc.md` in this directory is the study — read from the Library of Congress's own pages and from the
schedule PDFs (`LCC_Q2024TEXT.pdf`, `LCC_Z2024TEXT.pdf`, the class outlines), with every caption number
quoted verified out of the text files rather than from a summary.

Five mechanisms in LCC that our store lacks, each with a measurement already on the record next to it:

| LCC mechanism | What we do instead | Measured cost of ours |
|---|---|---|
| **Address and access are separate systems** (call number vs index terms + `Cf.`/`see` edges vs LCSH headings) | one `class` column doing both | 20.3% of rows have no address at all; unscoped contamination 41-84% |
| **Retire, never renumber** (`(667.6-.63)` obsolete numbers kept with a `see` reference) | a re-cut rewrites `class` on 575-863 rows | the tier-2 cartridge is valid only for its exact bytes, so every re-shelve invalidates a pin |
| **Literary warrant** (a caption exists because material exists, by approved proposal) | a keyword map written before the collection existed | 5 shelves wider than the block = 74% of the store; cosine re-cut beat it on reach (0.947 → 1.000 on POL/ARSA) |
| **Captions carry scope notes** (`Including …`, `Class here …`, `For X see Y`, `Cf. …`) | bare token lists in `CLASS_MAP` | an extractor's shelf choice is unfalsifiable; 18% of rows land in `wild` |
| **Sortable numbers, spans, adjacency** (`Z699+`, `E201-298`, `76.9.A-Z` Cutter expansion) | `class LIKE 'POL%'` — subtree only | no way to ask for a fact's neighbours; "more context per hit" is the one lever left at 0.936 coverage |

Two of them landed as code today, because the roadmap needed them anyway: `MEM/CRG.3.431` (M3 cartridge
banks) was **rejected by our own validator** — the regex allowed one dotted tail, so no Cutter or part
number could be stored, including the form `class_name`'s docstring advertises. It is legal now, and the
subtree predicate is boundary-exact in both arms (`QA76.9` no longer answers for `QA76.95`; SQL filter
measured 0.05 vs 0.04 ms on the 2,796-row store, i.e. free). Details in `docs/MEMORY_CORE.md`, "Shelf
isolation".

Two more are queued as experiments, not decisions:

- **Subjects table (many-to-many, LCSH-shaped).** Falsifier: route with headings instead of with the
  single shelf and compare against tonight's routed arm (leak 1.4-36.8%, reach unchanged). Fails if leak
  does not fall or reach moves.
- **Adjacency arm.** Fill the block's free slots by call-number neighbours of the top hits rather than by
  next-best score. Falsifier: rendered-block gold coverage (the metric that predicted accuracy at
  +0.048 → +0.040). Fails if coverage does not move — and it needs the document spine (backlog item 7) to
  mean anything, which is where the books-and-chapters design and LCC meet.

## Ranked enhancement backlog

Ranked by (measured or documented payoff) / cost, with the falsifier stated before the run. Items 1-4
attack the **reasoning residual** (244 of 346 wrong lines had every gold session present) or the
**temporal category** (0.465, the worst type); items 5-8 attack growth and hygiene; 9-10 are
instrumentation that makes everything else attributable.

**Re-ordered by what got measured the same night the list was written.** Item 1 is verified positive (facts
naming an absolute date: 0% → 75%, facts/turn flat, +3 chars, zero geometry voids). Item 3 — the subject
axis, the last open retrieval idea — is **measured no at this size**: gathering by shared rare-token subject
moved coverage on **4 of 470 questions** and lost 0.003 overall, so the fusion already surfaces what an
entity index would go and get below ~11k rows. Items 9 (rank provenance) shipped and paid for itself within
the hour. That leaves **presentation (item 4) and the write side (items 1 and 8)** as the only live
hypotheses for the 24% that remains, with the scale question handed to the S-split.

1. **Ground the extractor: feed it the last-k turns plus an observation date.** Source: mem0
   `main.py:922`, `prompts.py:524-535`. Our `curate_loop.py` extracts one turn in isolation, so pronouns
   and "last week" are written ungrounded — which is *the* mechanism behind the temporal failure the
   diagnostic described ("an ordering question needs three dated events"). Cost: **zero extra asks**, same
   4 asks/turn, longer prompt. Measure: temporal-reasoning accuracy on the venue (3 repeats) plus the
   right-fact-in-block probes; falsifier: temporal moves < 1 repeat-band while junk rate (measured by
   `m4_families.py` pairs) rises, meaning grounding bought verbosity rather than dates.
2. **Render validity into the block and teach event-time vs mention-time.** Source: Zep's context renderer
   (`retrieving-context.md`, `zep_longmem_eval.py:29-44`); Graphiti exposes the same as query predicates.
   Zero retrieval compute — it is a formatting change to `_render_block`, plus an `at=` filter (~20 lines
   against columns that already exist). Measure: temporal + knowledge-update slices with right-fact-in-
   block held flat (so it cannot hide behind coverage); falsifier: no movement on either slice while the
   muted control stays at `idk`.
3. **A subject axis, gathered rather than filtered.** Converged independently: Graphiti's entity rollup
   and mem0's subject index with a degree penalty (`main.py:1807-1821`,
   `boost = cos * 0.5 / (1 + 0.001(n-1)^2)`). This is NOT the shelf axis that died today — a category
   filter narrows, a subject gather *collects the multi-evidence set an ordering question needs*. Build
   it in the curation loop (not the write path), as a `subject` column plus a rollup table. Cost: one
   column, one table, no LLM. Measure: `lme_retrieval_ab.py --offline` (multi-session and temporal
   coverage are the target columns), then the venue; falsifier: coverage at k=16 does not move, which by
   the filed causal chain means accuracy cannot move.
4. **Presentation, not placement: purpose strings and an evidence-then-answer shape — the ordering half of
   this idea is already dead.** Source: Letta's core-vs-deferred tiers with a per-unit `description` saying
   what each unit is FOR, plus Cognee's deterministic answer-grounded evidence block (stopword-overlap
   filter against the generated answer, 160-char snippets, `file #seq` locators, `references.py:277-360`).
   The budget is measured dead and so is position: `tools/lme_posrank.py` finds no monotone position effect
   across 1,500 filed lines, so moving a fact earlier buys nothing. What has NOT been tested is what the
   line SAYS — 96 undifferentiated sentences versus a reader that can tell which kind of statement each one
   is. Cost: prompt shape only, no retrieval compute. Measure: venue accuracy, 3 repeats, same store, with
   coverage held flat (so it cannot hide behind evidence arrival); falsifier: a tiered/labelled block moves
   nothing either, which would say presentation cannot pay at all and the residual really is the reader
   model — a useful negative, because it ends the presentation line and points the next hour at the
   extractor instead.
5. **Empty the WILD bucket — but for the right reason.** Measured: a wild row is **4.5x more likely to be
   missed**, 18% of rows, half the misses. The falsifier written before the mechanism was checked has
   already fired analytically: `class` is not a ranking input anywhere (`serve/memory.py:910-915` uses it
   only as a `like` filter when a caller names shelves, and the blend reads rank/recency/confidence), so
   re-shelving a wild row cannot move it in the block. Keep this item for what it genuinely buys — human
   navigation in the UI, cartridge eligibility (`class_prefixes`), and filtered tool calls — and take the
   retrieval half of the 4.5x to item 3. Sources for the mechanism: Cognee's shelf telemetry +
   canonicalization (difflib cutoff 0.8, annotate-don't-reject), Graphiti's centroid subclasses. Cost:
   offline backfill, no LLM.
6. **Deterministic gates and scoping before every expensive judgment.** Source: Zep runs identity ->
   exact-name -> MinHash Jaccard >= 0.9 behind an entropy floor and pays the LLM only for the residue
   (`dedup_helpers.py:31-86`); its pair-scoping is what makes its write cost store-size-independent. Ours
   is already linear per scope but the exact-text dedup scan is O(scope) — the wall named at ~50k rows.
   Cost: index work, no LLM. Measure: writes/s into a 50k-row synthetic scope; falsifier: no slope change.
7. **Document spine: `documents` table + `doc_id` + dense `seq` + a tiling assertion.** Source: Cognee
   `incremental_chunking.py:53-66, 309-321` — and their own skeptical finding, the spine buys **citation
   and deletion, not precision** (they exclude it from fact comparison and never use it to widen a hit).
   Our `{file, n}` is already 90% of it; ~80 LOC, zero inference. Measure: a citation-resolvable rate on
   `ingest-*` answers, plus passage reassembly for the reader; falsifier: answers do not cite better, in
   which case it stays a deletion aid and gets deprioritized honestly.
8. **Junk pre-filters on the curation path.** Source: mem0's failure taxonomy (#4573: boot-file restating
   52.7%, recalled-context re-extraction — the last is exactly our self-feeding exposure). Cuts ~half of
   4 asks/turn. Measure: rows written per sweep and `m4_families.py` pair count, with right-fact-in-block
   held flat; falsifier: fewer rows but lower coverage, i.e. the filter ate evidence.
9. **Per-arm rank provenance on every hit.** Source: Letta returns `vector_rank`/`fts_rank`/
   `combined_score` per hit; we fuse and throw the evidence away. Pure instrumentation, no behaviour
   change, and it is what would have made the -0.139 diagnosis take an hour instead of a day. Measure:
   nothing — it makes the other nine measurable.
10. **Enum-constrained ids in the curation tool schema + a validate/re-patch loop.** Source: LangMem's
    `RemoveDoc.json_doc_id` validated against exactly the ids shown, with re-patch retry
    (`trustcall/_base.py:1192-1213`). Kills hallucinated supersede targets. Cost: 1-2 h. Measure: the
    existing merge audits; falsifier: no change in bad-target rate (i.e. the model was never the one
    picking wrong ids).

Deferred with a stated trigger: the query router (Cognee) and shelf densification return only at 10k-100k
rows — today's numbers are scoped to 600-2,655 and the venue store is the place to re-run them;
communities/hyper-edges/BFS expansion need a graph DB; anything needing an LLM per write or per read is
out while the single GPU serves the engine.

**Trigger fired and the first half returned (2026-10-17):** the venue store is 10,973 rows, and the router
shipped behind `memory.route_shelves` (off until the venue re-record gate) — reborn not as the recall lever
this table killed but as the contamination lever `m4_shelfcall.py` measured (leak 2–5× down, reach
identical). See docs/MEMORY_CORE.md, "The router shipped as production code". Shelf densification is still
deferred: the cosine-cut probe showed the cut only pays once something calls it, and that something now
exists.

---

# The pass of 2026-11-23: three more systems, and the switch question

The owner asked the comparative question directly — agentic-graphrag vs Hindsight vs Obsidian vs what we
built, and "should we just take from each to better our own system?" — and named the weakness to weigh:
**the graphing pass and how long it takes.** The verdict and the port arithmetic are in
**[DECISION-2026-11-23.md](DECISION-2026-11-23.md)**. Three new reports sit beside this file:
`agentic-graphrag.md`, `hindsight.md`, `obsidian.md`. Same method as the 2026-10-14 pass: primary sources,
code over README, a `## Unverified` section per file.

| system | file | what it is the best witness for |
|---|---|---|
| agentic-graphrag (ontogr) | `agentic-graphrag.md` | a schema the extractor cannot step outside, tiered entity resolution that links instead of merging, and decisions that go stale when their sources move |
| Hindsight (vectorize-io) | `hindsight.md` | the consolidation rung we lack: observations with proof counts, pages read as a database read, and zero LLM calls on the read path |
| Obsidian | `obsidian.md` | the file as the identity and the index as a cache — with no ranking, no types, no consolidation, and 10,791 plugins bolted on to cover it |

## Cross-cutting finding 5: the graph is the weakness, and it is a read-path bug wearing a performance hat

Measured on this box, 2026-11-23, all numbers live:

- The last pass: **3,187 s, 1,079,123 tokens in / 323,288 out**, reading 1,183 of 3,819 active facts
  (**31% coverage**), with 612 rows queued behind it. At the store's 150-234 facts/day that queue refills
  in ~2.6 days, so a full-store pass at that rate is ~103 min of GPU, every ~2.6 days.
- The pass is **decode-bound** — 273 output tokens per fact at ~90 tok/s — which the module docstring
  already said. Chunk size is tuned to the 16,384-token ceiling, so there is no batching win left.
- **Two thirds of what it builds is thrown away at the seam.** `_graph()` maps node ids to row ids with
  `rfind("_fact_")` and keeps an edge only when both ends parse: **1,020 of 3,133** edges. 1,327
  fact→concept and 786 concept→concept edges are dropped, so the concept layer — the reason to build a
  graph — is a dead end, and the arm is one hop.
- The cheapest alternative is measured: **a k=8 vector graph over all 3,755 facts costs 0.423 s and
  0 tokens** and yields 15,020 edges at 100% coverage. 7,535× faster, 4.8× more edges. What the LLM layer
  uniquely buys is the **1,913 concept nodes** — abstractions no single row carries.
- 1,608 communities over 2,136 rows = **1.33 rows per community**: the community layer consolidates
  nothing. Five of the twelve god nodes are export artifacts (`USR — part 1 (25 facts)`, degree 26 =
  `FACTS_PER_FILE` + 1), and the owner is three nodes (`Eugene`, `Dustin (goes by Eugene) — owner`,
  `Dustin — the user`) because `_merge_extractions()` is pure concatenation with no entity resolution.
- The store's own typed edges — 858 rows, **all `kind='about'`** — cast no vote at all.

So the answer to "the graph pass is too slow" is not one faster pass. It is **three layers at three
prices** (typed links free / vector kNN 0.4 s standing on every write, as Hindsight materializes at insert /
the LLM concept pass as a slow top coat), plus walking the concept nodes. Annotation on the 2026-10-17
line above: "communities/hyper-edges/BFS expansion need a graph DB" is now **false** — the graph is built
in-house (`terminal/strata/graphify/`) into a JSON sidecar beside the store, and a full cosine scan is the
honest design at this scale.

## Cross-cutting finding 6: the field moved to small dedicated models for the memory judgments

Two of the three systems, independently, and both measured the win:

- **Hindsight** ships `hs-decide-1-flash` (0.8B, Apache-2.0) for the judgments inside recall,
  consolidation, reflect and pages — "a typed answer instead of text to parse" — gated on
  **self-consistency** because tuned per-model confidence bars "let a hedging model… settle nothing".
  Their claim: ~40% fewer consolidation LLM calls at the same pass rate, ~167 ms median against 1-7 s.
  Plus `hs-rerank-1` (114M, MIT) as the default local reranker, so recall bills zero LLM calls.
- **agentic-graphrag** makes the same bet with **GLiNER**: a compact encoder that extracts any declared
  entity types, runs on the machine, reads every chunk, and returns confidence scores — with `hybrid` mode
  sending only the low-confidence chunks to the LLM, up to a budget.

Strata spends served-model asks on exactly these judgments: the shelf clerk at a 1,400-token budget (whose
shelf moved between two identical asks **2 of 4** times at temp 0.8), the listwise reranker, and the graph
pass. Every one queues behind this conversation on one 4090.

## Cross-cutting finding 8: four external systems fuse with RRF at k=60; we ship k=1

agentic-graphrag (`search.py:89-108`, "ranks only, raw scores discarded"), Hindsight
(`search/fusion.py`), and — from the 2026-10-14 pass — Graphiti and Zep all use the paper's conventional
k=60. We reset to **k=1 on 2026-10-15** by sweeping our own venue copy (10,973 rows, 500 questions,
deterministic: top1 0.517 / top3 0.849 against 0.504 / 0.823, ≥ at every width), and the reach probe
scored identically at 1 and 60, so the property that justified rank fusion survived. Four systems at 60 is
not evidence that 1 is wrong; it is the strongest outside signal that the constant deserves a **re-measure
at the current store size** — 3,819 facts and 33,475 chunks, a different corpus shape than the venue copy
it was swept on, with the doc family now dominating the candidate pool and BM25 stats scoped per family.
Instrument: `tools/lme_retrieval_ab.py --offline` (~45 s), then the panel. Falsifier: k=60 ties or loses
at the block's own width, and k=1 stands.

## Cross-cutting finding 9: the maturity spread is the decision's hidden axis

| system | stars | licence | hands on the wheel | version | benchmark evidence |
|---|---|---|---|---|---|
| Hindsight | ~62,900 | MIT | ~291 contributors, 78 releases, weekly→several/week | 1.2.3 | LongMemEval-S 500 q, self-judged (GPT-OSS-120B), a public ~100-case eval suite, 221 open issues |
| agentic-graphrag | 84 | Apache-2.0 | **2 authors**, 181 commits, 0 open issues | **0.0.8** | five "lite" runs, **n=1-2 questions each**, self-judged; 91.13% coverage, 2,323 tests |
| Obsidian (the pattern) | 53,555 (skills repo) | MIT + free app | 10,791 community plugins | app 1.9-1.12 | none — it is a format, and the ranking comes from QMD (31,480★) beside it |

Read as a risk table: Hindsight is a moving target with a big surface (a schema renamed twice in ten
months, ~120 migrations); agentic-graphrag is pre-1.0 with "breaking changes expected" in its own
`AGENTS.md` and a fixed vector placement (changing the embedder means an empty database); the vault is the
only one of the three that is a format rather than a service, which is why it is the only one that ports
without a lock-in clause. Our own exposure is the reverse: one Postgres, one file per fact, the vectors
inside, and a schema we control — the four-knob-and-a-cutter taxonomy is the part with no external
dependency at all.

## Cross-cutting finding 7: the two cheapest structural wins in the whole directory are shape, not machinery

Ranked by payoff per unit of cost, from the 2026-11-23 pass, both attack failures we have measured and
never fixed:

1. **Compute the time mark in code, let the model read it** (Hindsight
   `consolidation/prompts.py:156-162`). Facts arrive out of order, so the consolidator labels candidates
   `(stated after this fact)` and sets `newer_than_input_facts: true`; the model is told "the most recently
   stated value is the current one — not the fact processed last". Their ablation: **29/40 → 36-38/40** on
   the consolidation evals, *with no code checks and no second call*. For us: a boolean against `when`.
   Temporal is our worst slice (0.465). Zero new models, zero new indexes.
2. **Three budgets, one per kind of text** (Hindsight `engine/fact_budget.py`): facts, evidence
   (`source_facts`), and passages (chunks) each under their own cap, with skip-not-evict and a floor of one
   whole result — "an empty answer reads as 'this bank knows nothing about that', and a fact clipped
   mid-sentence would be a claim the memory never made". Our complaint, in our own words: the block's
   budget "is spent on this afternoon's sentences", and only 4% of 2,964 facts are never recalled. Split
   `turn_block_chars` into three.

## The benchmark note, updated

Hindsight is the first system in this directory whose headline number comes with a public, per-model eval
suite (`hindsight-system-evals`, ~100 category-labelled judged cases, failures explained, "a single red run
is a signal to re-run, not proof of a regression"). That is our bench-panel discipline in public. Its
numbers still need the sentence: **91.4% on LongMemEval-S is Hindsight's stack on OSS-120B with Gemini-3
Pro as the answer generator, judged by GPT-OSS-120B at temp 0.0 (their own judge); the apples-to-apples
row is 89.0%; the "independent" reproducers are on the author list; and paper §7.3 ships literal `<add>`
placeholders for the retrieval token budgets.** The shipped schema has three layers, not the paper's four
— the opinion network and its `confidence_score` were dropped in a migration.

