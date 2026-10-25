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

**What we believe (challenge this).** C's gap = (1) GDN layers compress away Q-addressable detail
(the GDN paper's own motivation), (2) extraction ≠ associative recall (Mamba-3 2603.15569 names
this split), (3) the trained indexer was never trained to route question-queries into
not-recently-written cells at answer time.

**Asks.**
1. ADVERSARIAL: the merge-0.433 vs mam-0.100 spread — prose-vs-numbers, or length/recency/order?
   What confound would embarrass us? (All carts ~600 tokens, ledger-name order, same procedure.)
2. LITERATURE: 2025-2026 work on answering from restored KV/recurrent state WITHOUT re-feeding the
   source text — esp. on GDN/Qwen3-Next or NSA-indexer models. We have: Memory3 (2407.01178),
   ICAE (2307.06945), Based (arora24a), hybrid analysis (2507.06457), Mamba-3, StreamingLLM sinks.
3. SANITY: does Grok's own architecture (its sparse-attention lineage) show the same
   read-your-own-state weakness? If so, is the fix trained (reader LoRA / read marker) or arch?

**Cheapest probes on our side (running next).** P1: re-mint the number-dense cart as prose,
re-run its 10 state-only golds — if it jumps to narrative-level, we have a MINTING LAW for carts.
P2: STRATA_KV_ROT=1 (rotating-KV arm; sinks stay pinned). P3: widen QSA selection (engine work).
