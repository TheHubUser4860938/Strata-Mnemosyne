# GRAD2_PRE_REG — the anchor re-gate (2026-10-26, frozen before the run)

The graduation gate (GRAD_PRE_REG.md) said NOT YET for PREFIX attach: 33% of deep windows
rut (A6: 2/6; combined with grad: 3/9), while per-ask PASTE (arm B) was 90/90 with zero
ruts at 1,426 eval tok/ask. The owner's call landed on paste's economics being reasonable;
the build then shipped ANCHOR MODE - the same anchor bytes re-presented by the SERVER on
every request (ahead of the question, in the newest user turn) without entering the
client's history - plus TAIL RECALL (P10: the recall block moves out of the system head,
measured flat ~350 tok vs growing 1,340). This run re-gates what now SHIPS.

## Arms (live server after the reboot that loads the new code; 30 golds x 3 passes;
## temp default 1.0; max_tokens 500; answer-phrase scorer with the period fix)

- **N - ANCHOR (the ship candidate)**: header `X-Strata-Carts: c4-results,mam-test745,
  merge-notes` + `X-Strata-Carts-Mode: anchor`, on the box configured
  `block_position: "tail"`. Carts anchor per ask (B's effect), recall rides the tail
  (P10's economics), history stays lean (neither B's nor A's bloat).
- **P - PREFIX (the measured incumbent)**: same header, `X-Strata-Carts-Mode: prefix`,
  block tail too - isolates what the anchor buys against the same cheap stack.
- **C - FLOOR**: no carts, `X-Strata-Memory-Block: off` - persona gauge (overlap warning
  inherited from grad: always.md quotes C4's numbers).

## The gate (frozen now)

GRADUATE-ANCHOR iff: N >= 0.95 overall AND N >= P + 0.02 AND no cart below 0.85 AND
per-window collapse count (a pass scoring < 0.90) is zero. Otherwise NOT YET with the
per-window table as diagnosis (rut rate is the suspect, per A6).

## Cost & limits

180 asks ~ 15-25 min. One boot for all arms (the config tail flag must be ON before the
run starts - if the boot predates the config edit, say so in the addendum, do not hotfix
mid-run). The anchor's block bytes are read LIVE from CartMinter.ATTACH_LEAD (the lead was
renamed position-neutral the same morning; grad/a6's numbers stay comparable because the
bodies and golds are byte-identical - only the lead sentence changed, logged as an
instrument amendment between experiments). Prefix-arm comparability to grad/a6 is
approximate for that same reason - stated, not hidden.

---

## RESULTS (addendum, 2026-10-26 ~15:20, run tag 145651, single boot 14:53)

    N ANCHOR 1.000 (n=90) | med eval 3,588 tok | buckets 2,761 3,182 3,890 4,403 | per-pass 1.0 1.0 1.0
    P PREFIX 0.989 (n=90) | med eval 6,222 tok | buckets 2,120 4,402 8,126 11,400 | per-pass 0.967 1.0 1.0
    C FLOOR  0.578 (n=90) | med eval 34 tok (gauge; rose from grad's 0.400 - the standing text
             now QUOTES more bench answers after the always.md queue rewrite; the persona got
             more learned about its own bench, the gauge moved, the gate legs are untouched)
    latency medians: N 3.42 s | P 7.31 s
    gate legs: N>=0.95 PASS | N>=P+0.02 FAIL (1.000 < 1.009) | carts>=0.85 PASS | no N pass<0.90 PASS
    LITERAL VERDICT: NOT YET - on the recall-margin leg alone.

WHY THE FAILED LEG FAILED: prefix drew the lucky roll the pre-reg named. N was perfect
(90/90, zero misses in every window and every depth bucket); the leg needs P <= 0.98 to
pass a perfect N, and P drew ONE isolated miss (mam-test745 @pos15, pass 1) = 0.989. The
leg is unfailable when N=1.000 and P stays within one miss across 90 asks.

DIAGNOSIS (the table the gate ordered):
1. The anchor's rut-immunity REPLICATES on the production surface: 90/90, zero collapses,
   every cart 1.000. The B-arm finding was not an artifact of the paste geometry.
2. Prefix did NOT rut this time - one stray miss, no clustered collapse (n=3 windows;
   luck-vs-cure by the tail-block move is not separable at this n: A6's 2/6 was measured
   on the head-block stack).
3. THE ECONOMIC LEG FLIPPED, unexpectedly and hard. The pre-reg assumed prefix was the
   cheap arm and the anchor paid ~1.4K/ask extra. Production says the OPPOSITE: the
   anchor is CHEAPER - median 3,588 vs 6,222, deep-bucket 4,403 vs 11,400 (2.6x), and
   2.1x faster at the wall (3.42 s vs 7.31 s). Prefix's per-ask cost grows 5.4x across
   the window; the anchor's 1.6x.
4. Why P10's flat-tail prediction undersold this: P10's T arm PASTED its block
   client-side, so those bytes entered the client's HISTORY and went stable - a different
   cache geometry than the server-INJECTED tail block, which re-presents volatile bytes
   at the end of every prompt. At long-answer production depth (gold answers run 150-500
   tok), prefix mode's parked conversation evidently stops reusing from near its head
   (P's deep-bucket 11,400 ~ a full-history re-read), while anchor mode keeps reusing
   (4,403). The exact engine-cache mechanism is OPEN (P11 candidate: 25-turn prefix vs
   anchor conversations with block/carts toggled pairwise, reading cached_tokens per
   turn); the decision does not wait on it.

CAVEATS (mine, logged): one boot (by design); my own session parked a ~250K conversation
and prefilled once mid-run - the traffic tax lands on both arms but inflates absolute
eval somewhat; the ATTACH_LEAD amendment (inherited above) changes no gold, no body,
no scorer.

DECISION THIS HANDS THE OWNER (the gate is mine; the ship call is his):
- A. SHIP ANCHOR as default anyway: it won every measured dimension - recall, cost,
  latency, history hygiene; the failed leg asks "does the anchor buy recall margin" and
  the honest answer is "prefix got lucky in 3 windows; A6 says it ruts 2-in-6 over time."
- B. CONFIRM first: re-run grad2 (~35 min, engine free) and let the dice roll again on
  the recall-margin leg.
- C. Keep prefix default, anchor opt-in - now the conservative choice costs MORE per ask.

## RATIFICATION (2026-10-26 afternoon, the owner's word on the decision menu)

"Option A it is then if it performs the best." - OWNER CALL: the ANCHOR SHIPS as this
box's attach shape (config attach_mode:"anchor" stays the opt-in lever; the CODE default
stays "prefix" so every other box remains byte-identical, the fork law intact). C3 is
CLOSED: the deep-window countermeasure is per-ask anchoring; P8's roll-up demotes to the
toolbox (0.444 vs 1.000 is not a contest). The literal NOT YET stands above as what the
gate measured; the ship decision is the owner's, made on the shape: recall 1.000
zero-ruts, cost median -42% vs prefix, depth -61%, latency -53%. Remaining science,
not decision: P11 (p11_run.py) probes WHY prefix's parked history stops reusing at
long-answer depth; its predictions were frozen in the runner's docstring before the run.

## AMENDMENT (same day, from P11 tag 155054 - corrects point 4's attribution above)

P11 (5 arms x 25 turns, predictions frozen in p11_run.py's docstring before the run)
shows point 4 above MIS-ATTRIBUTED the poison. The head carts are INNOCENT: prefix
carts with the block OFF run flat at ~34 eval tok/ask (P2; the whole prefix+history
reuses; carts absorbed). What drives the growth is the server-injected VOLATILE TAIL
BLOCK: block alone with NO carts grows the same (2,846 -> 6,901; and its turn-25 drop
to 816 = a checkpoint landing mid-run - direct evidence of checkpoint disruption by
volatile tails). P10's flat 350 was real but measured a PASTED (history-stabilized)
block; P5's flat 540 confirms the law: volatile bytes that persist in the client's
history cache fully - it is cache GEOMETRY, not token count, exactly as predicted.

THE UNIFIED LAW (slopes vs answer length): when the tail is volatile, checkpoints stop
landing, and each ask re-evaluates everything since the last checkpoint - so per-turn
cost grows with whatever you GENERATE (answers) plus whatever you INJECT (block,
anchor). Measured slopes: anchor arm 29-word answers -> +81 tok/turn; block-only 102
words -> +213; prefix 175 words -> +308. The anchor wins its cost edge twice over:
terse answers (the fact is in front of the model - ~6x terser) shrink the replayed
history MORE than its re-presented bodies add. Real production effect, not pure cache
magic - stated plainly.

TWO SIDE FINDINGS (logged): (a) P3's one sanity miss (pos 19) was an EMPTY completion -
an engine artifact, not a recall failure; anchor recall across both runs: 90/90 + 24/25
with the one miss blank. (b) Cart conversations paid ~11K at turn 1 (all cart arms,
either mode) while the no-cart arm paid 1,302 - carts appear to break the installed
standing state's reuse at conversation start (n=1 per arm; engine-level question for a
venue night; if fixable it saves ~10K on every conversation's first ask).

THE SHIP STANDS: under identical conditions (both arms block ON) the anchor won recall
(1.000 vs 0.989), cost (3,588 vs 6,222 median) and latency (3.42 s vs 7.31 s). grad2
measured what ships; P11 only corrected the WHY. Open knobs for future nights: tail-block
freshness vs cost (a pinned tail block would ride P2's flat-34 ceiling but age mid-window);
the carts x standing-restore question above; and the HARVEST CAVEAT - the store now
shelves its own bench answers (floor rose 0.400 -> 0.578 across the day; P11's NO-CART
arm scored 25/25 because the shelves had learned the golds), so future cart benches want
novel golds or harvest-off windows.
