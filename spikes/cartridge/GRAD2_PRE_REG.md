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
