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

---

## RESULTS 2026-10-26 (run tag 190304, standing 77e296bc at start; added after the run,
## predictions above untouched)

    VERDICT: NOT YET  (gate: A >= B - 0.02 overall, no cart below B - 0.15)

    arm     raw     re-scored   med eval/ask   shape
    A attach 0.867   0.878      1,967 tok      per-pass 1.000 / 1.000 / 0.633
    B text   1.000   0.989      1,426 tok      flat, 90 windows of one strong anchor each
    C floor  0.500   0.400         35 tok      gauge, as warned (persona overlap real)

1. THE GATE HOLDS UNDER CORRECTION. The re-score is not cosmetic: the shared NUMTOK
   matcher could not see a number wearing its sentence period ("...rate 0.06.**"), a
   relative of the G3 period-fix family - fixed at the root between experiments (g3_run.py
   comment, 2026-10-26) and both arms re-scored. The fix moves numbers both ways (A +, B -,
   and C's loose credit nearly halves); the gate verdict is unchanged. Raw numbers above
   stand as the record; re-scored are the true ones.

2. THE SHAPE IS THE STORY, NOT THE MEAN. The A arm was TWO PERFECT WINDOWS (60/60
   re-scored across passes 1-2) and ONE collapsed tail (pass 3: 20/30, every miss at
   positions ~19-30: six "I don't know" and four a self-reinforcing cross-cart loop -
   three consecutive merge-notes golds answered "According to the MAM reference
   note...", each wrong answer feeding the next). Depth and trajectory-luck both explain
   it; n=3 windows cannot separate them. A6 (six more A windows, launched 2026-10-26)
   exists to price the rut rate: near zero = ship-shape shallow windows, trajectory was
   unlucky; >= 1/3 = depth is the default enemy and S4b must land before default attach.

3. PRODUCTION ECONOMICS CORRECTION (mine, public): last night's report told you "the
   conversation cache absorbs the prefix at ~33 eval tok/ask" - that number is BENCH
   GEOMETRY (block-off). The grad rows measured block-ON production: A's median is 1,967
   eval/ask and GROWS with depth (1,076 -> 2,350 -> 3,608 by position bucket) while B sits
   FLAT at 1,426. The usage fields fingerprint the cause (inferred, not engine-traced):
   the tier-3 recall block rides between the carts and the conversation, and its bytes
   change every turn with the query - so every turn re-evaluates block + all history
   behind it (A's growth), while B's fat constant user-turns keep the block stable and
   pay only the new turn. The carts ride cheap; the BLOCK does not ride free. Candidate
   fix (P10, designed not built): move the recall block to the tail (after history,
   template-safe as a final user-side merge) - predicted: history caches again, cost goes
   flat like B's, carts stay absorbed. If it measures, attach's real cost is a fraction
   of what tonight's numbers say.

4. MID-RUN ROTATION OBSERVED: the standing rotated 77e296bc -> 74ae0322 at 19:08, DURING
   this run - my always.md residency-correction edit rotated it on the next standing
   request, no reboot needed (closes last night's open question about the trigger; my
   "not until boot" prediction was wrong - the trigger is live by design). Production
   conversations survived per design (the re-seed installs the slot's K/V; parked
   conversation states are untouched) - no arm's rows show the event.

5. WHAT NOT YET MEANS FOR SHIPPING: attach is already the product's opt-in task-scoped
   path (the owner's C1), and for windows that open and close inside ~20 turns tonight
   says 60/60. NOT YET blocks the DEFAULT-ON and the deep-window claims, not the feature.
   Paste-the-text (B) remains the recall gold standard at ~1.4K/ask and its per-ask anchor
   is immune to the rut (90/90) - the design lesson the S4b note now carries: distance AND
   rutting are what the tail anchor cures, and re-anchor cadence is the pull header we
   already shipped.
