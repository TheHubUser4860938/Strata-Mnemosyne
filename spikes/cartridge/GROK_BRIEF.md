# Grok brief — the state-only read on a GDN hybrid (2026-10-25)

**What we have.** Strata Mnemosyne: a memory system that can (a) compose knowledge into an
llama.cpp-style session state file once, then re-send the same bytes as text each turn and let
prefix cache absorb them ("composed", arm A), or (b) ask questions against the restored state with
NO text re-sent ("state-only", arm C, the MAM-cartridge dream: ceceli33/titan-cognitive-core-v3,
TEST745, whose state-only READ worked on a dense 72B).

**The measured result (Gate 3, n=90 per arm, 30 marker golds, temp 0.8, 3 passes).**
Composed arm: 0.900-0.967 recall at 37 eval-tokens/ask. Text-injection control: 0.933-0.967 at
1,512 tok/ask. State-only: **0.278** — but cart-driven: narrative cart 0.433, mixed 0.300,
number-dense cart 0.100; 47% honest refusals (the model senses prior context, can't extract from it).
Same rows, body re-sent as text = ~0.97. Storage isn't broken; the read is.

**Our model.** Qwen3-Next-family hybrid: 3:1 Gated DeltaNet (linear attention, fixed recurrent
state) + sparse-attention full-K/V layers with a TRAINED indexer selecting top-k K/V cells per
query (NSA-style). Session restore is byte-exact (KV int8 streamed, MTP spec-4); our engine's fast
kernels are exactness-preserving, so the sparsity is the model's, not ours.

**What we believe (challenge this).** P1 (2026-10-25, same-day probes, n=30 per cell) KILLED two
hypotheses and left one standing. Content STYLE: re-minting the number-dense cart as fluent prose
moved state-only recall 0.10-0.20 -> 0.07-0.10 (no lift; cart-health control read 0.90-1.00).
POSITION: moving that cart's body to the final compose slot (recency) gave 0.067 (no lift). The
SURVIVOR is FACT DISTINCTIVENESS: merge-notes (unique strings: hashes, version triples, branch
names) replays at 0.367-0.433; mam-test745 (small shared numbers: eleven, 8, pending) sits at
0.067-0.200 across three same-day runs; the hits in the replay are almost all unique tokens.
Mechanism guess: the trained indexer routes the question by query-cell similarity, so rare token
signatures are findable and common numbers are haystack.

**Asks.**
1. ADVERSARIAL, v2: with style and position measured dead the same day, the surviving read is
   TOKEN DISTINCTIVENESS (unique strings recalled at ~0.4, common numbers at ~0.1, reproduced).
   What confound survives that? Candidate ours: the golds themselves differ in difficulty
   (marker ambiguity - "eleven" vs "11"; answer length). What probe would falsify distinctiveness
   cheapest? We can re-mint any cart text we like; the gold questions are ours too.
2. LITERATURE: 2025-2026 work on answering from restored KV/recurrent state WITHOUT re-feeding
   the source text - especially on GDN/Qwen3-Next or NSA-indexer models, and especially anything
   that quantifies sparse-attention retrieval by token rarity/uniqueness. We have: Memory3
   (2407.01178), ICAE (2307.06945), Based (arora24a), hybrid analysis (2507.06457 - recall hinges
   on full-attention layers; 3:1 is their floor), Mamba-3 (2603.15569 - recall vs extraction
   split), StreamingLLM sinks (2309.17453).
3. SANITY + REMEDY: does Grok's own sparse-attention lineage read its own restored state any
   better? And given our ladder - KV_ROT arm (free, reboot), wider QSA selection (engine work,
   risks the trained regime), trained reader (LoRA/read-marker; heavy: new quant lineage) - what
   would you run first on a 24 GB box?

**Measured today (all n=30, temp 0.8, 3 passes, tool off, block off).** mam state-only: 0.200 /
0.100 prose / 0.067 last-position; merge replay: 0.367 (G3: 0.433); c4: 0.300 in G3. Text-riding
controls never broke: composed arm 0.90-1.00 at 32-37 eval tok/ask. Records:
/home/eugene/Strata-data/bench/{g3,p1}/*.
