# GRAD_PRE_REG — the graduation A/B (2026-10-25 night, frozen before the run)

The pre-ship gate the owner approved (his C4 call: "go ahead, slot in where it makes
sense"): **does the product's attach shape recall as well as re-injecting the text every
ask?** G3 measured the bench geometry (compose + ack turn, 0.964 gate); this measures the
PRODUCTION shape over the wire: X-Strata-Carts with no ack turn, real dialect, temp 1.0.

## Arms (all live /v1/chat/completions, reasoning_effort off, temp default 1.0 per bench
law, max_tokens 500, block ON as production ships it, 30 golds x 3 passes each)

- **A - ATTACH**: header `X-Strata-Carts: c4-results,mam-test745,merge-notes` on every
  request of a 30-turn conversation (the golds ARE the turns - a task window asking its
  questions). The bodies ride the prefix; the conversation cache absorbs them (smoke
  measured: +400 tok once, then eval ~7-761).
- **B - TEXT**: no header; every ask's user message carries the full three-body text block
  (the same bytes as ATTACH_LEAD + bodies) re-injected before the question - the naive
  "paste the documents every turn" alternative at the measured 1,512-eval-tok/ask cost.
- **C - FLOOR**: header absent, block OFF (X-Strata-Memory-Block: off), no text - what the
  standing persona + world prior alone recall. NOT a gate leg (see overlap note): the
  standing queue line quotes C4's own numbers, and the carts' facts partly live on the
  shelves - expect this arm above the old probe floors.

## Golds

The frozen 30 from g3_run (answer-phrase style - the C5-v2 fold-in is already inside: the
classifier matches answer phrases, not prose). Cart split: c4 x 10, mam x 10, merge x 10.

## The gate (frozen now, countersign-style verdict after)

GRADUATE iff: overall A >= overall B - 0.02 AND no per-cart collapse
(A_cart < B_cart - 0.15 for any cart) - attach ships when it is not meaningfully worse
than pasting text, at a fraction of the prefill cost. Otherwise: NOT YET, with the
per-cart table as the diagnosis.

## Known honesty limits (fixed in writing, not after)

1. Persona overlap: always.md quotes C4 verdict numbers (1.000, 0.996, 100-500, 236 MB) -
   c4 golds may echo through standing text in BOTH gated arms (fair) and inflate C (noted).
2. The tier-3 block rides A and B; production ships exactly this stack, so the gate is
   stack-vs-stack, not cart-in-vacuo. C is the vacuo gauge.
3. Depth: 30 turns is the regime where the fresh-window economics apply (C3's session-
   scoped stance); deep-window decay is P8's domain, not this gate's.
4. Conversation shape: golds-only history (no chit-chat); P5 showed chit-chat history is
   symmetric harm to all arms.
5. One server boot (77e296bc standing), one engine generation, nothing else running.

## Cost

90 asks x 3 arms + the B arm's re-injected history growth ~= 20-35 min on this box.
Rows: bench/p1/grad_<tag>/grad_rows.jsonl; verdict appended to this file after the run
(the never-erase law: predictions stay, results are added beneath).
