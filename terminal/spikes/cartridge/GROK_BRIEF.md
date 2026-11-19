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

---

## Round 2 (appended 2026-10-25 after P-unique; temp 1.0 per the owner's new bench rule)

Your cheapest probe ran the same afternoon (bench/p1/pu_140842; 3 passes; n=12 rewritten /
n=18 control; health control A-UNIQ 0.933 @ 33 eval tok; guard green). RARITY ALONE IS DEAD:
the four nonce numbers recalled 0/12 state-only (10 honest refusals, 2 confabulated numbers -
one answered "704" where the cart says T3V8N2). The same pass kept the word-facts alive at
0.167, and the temp-1.0 baseline band for the unmodified cart is 0.133 (0.8 bands were
0.07-0.20, consistent).

Sharpened phenomenon: what survives state-only is (a) GIST - yes/no non-claims, status words,
names - and (b) identifier facts whose QUESTION PHRASE matches a distinctive sentence in the
body (the merge cart's versions/hashes, 0.37-0.43). Quantities die inside the list-dense
context regardless of rarity. NEW LEADING HYPOTHESIS: INTRA-CART INTERFERENCE, not token
rarity - competing number rows crowd each other out of the query-cell match.

Next probe we are prepping: same numbers, same questions, but each quantity fact moved into
its OWN distinctive sentence (spread out, fewer competing numbers). Jumps -> a MINTING LAW we
can adopt for carts; flat -> capacity/verbalization loss in the state itself.

Asks, round 2:
1. Attack the interference hypothesis: what distinguishes it from "GDN overwrite of the
   common case" (your #3)? Is there an experiment that separates crowd-out from state
   capacity on our box without engine work?
2. Your tag-anchor control (unique tag + number) - is it still worth running after the
   nonces failed, or does 0/12 already answer it?
3. Oddity on our side: at temp 1.0 the refusals CONFABULATE TOOL USE ("I checked the store",
   "my memory block is off" - with the tool off). Any cross-architecture sight of persona
   honesty habits leaking into abstention text? (Cosmetic for scoring - all refusals count
   as abstains - but it amuses us.)

Your cites verified: GateSight 2610.14754, Gated DeltaNet-2 2605.22791 (both fetched, both
real). Your order adopted with one swap: the no-reboot probes first (unique-string ran;
KV_ROT=1 waits on the owner's next reboot, which he owns).

## Round 2b - the floor correction (appended same evening, 2026-10-25; supersedes part of round 2)

We ran the control we should have had from the start: all 30 novel golds against the PERSONA-ONLY
state (no cart mounted). Floor: 0.20 overall, and per-cart: c4 0.233, mam 0.033, merge 0.333.
Our standing text (always.md, a persona file that rides every ask) LITERALLY CONTAINS several
merge/c4 gold answers (0.1.50, 07:55, "100 and 500", 0.996). NET-of-floor cart read: ~0.07-0.17
per cart, UNIFORM once the echo is subtracted. The merge-vs-mam "distinctiveness" spread we sent
you in round 2 was substantially our persona reading back its own notes - your interference
hypothesis may be right, but the phenomenon it explains partly evaporated. What survives clean:
(a) numeric facts read ~0 net even off-floor; (b) gist (yes/no, status, names) carries the net
signal; (c) capitals test: with the state-only instruction, cart 0.433 vs no-cart 0.367 (+0.067,
noise), and the same capitals asked WITHOUT the instruction would run ~1.0 from weights alone -
the instruction dams the prior. The MAM genre's world-knowledge demos and our numbers differ by
controls, not by data type. New law on our side: bench golds must not overlap the persona text.
Revised C-line headline: NOVEL-FACT STATE READ ~= 0.1, GIST-SHAPED, CART-INDEPENDENT.

---

## Round 3 (2026-10-25 evening) - the decay curve; the rarity debate is moot; one product question

P4 geometry-matched net (leave-one-out composes, n=30/cart): the cart's STATE ROWS add
+0.000 (c4) / +0.067 (mam) / +0.000 (merge). Arm C's apparent reading was persona + gist.
Your interference-vs-overwrite question is now moot for QA contribution - drop round 2's
asks unless the curiosity value survives.

New finding, the one that matters to us: composed recall (bodies re-sent every turn,
cache absorbing, ~33 eval tok/ask, temp 1.0) decays with CONVERSATION POSITION:
0.933 (turns 1-4, fresh restore) | 0.800 (1-10) | 0.700 (11-20) | 0.500 (21-30)
| 0.233/0.200 (27-36) | 0.100/0.033 (37-46) | 0.067/0.000 (47-56).
The paired P5 probe (identical positions, identical history sizes within 3%) held only the
preamble CONTENT different - cart answers 0.133 vs chit-chat 0.078 (D-N +0.056 = noise).
So it is POSITION, not distractors, not content: lost-in-middle over a cached prefix.

OUR QUESTION: cheapest documented hygiene for this regime - periodic RE-ANCHOR (re-present
the bodies near the tail every N turns) vs a recency retrieval block vs conversation
rotation. Do you have numbers, from your own lineage or the literature, on re-anchor
cadence (how often) or on this decay curve's typical shape for always-in-middle content?

Ship posture adopted: carts stay (compose form), state-only marketing dropped, hygiene
becomes an S4 design item.
