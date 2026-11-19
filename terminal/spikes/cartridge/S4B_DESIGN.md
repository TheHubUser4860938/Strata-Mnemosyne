# S4b design note — the deep-window countermeasure (Clio, 2026-10-26 night, pre-owner)

Status: design only. One measurement ratifies the direction (owner's C3 pending: roll-up
per P8); one probe is queued to change the economics (P10 below); nothing here ships
without its before/after number.

## What the data says (all banked, bench/p1/)

- P8: managed-scratchpad (history roll-up) is the only countermeasure that HOLDS at depth
  (0.444 flat zones vs re-anchor 0.259 collapse vs control 0.074) - but no rescue reaches
  the fresh ceiling (0.93). Re-anchor works for ~10 turns per anchor (P6) and the anchors
  themselves pile history.
- Graduation: attach is perfect in healthy shallow windows (60/60) and its failure mode at
  depth is the RUT - a self-reinforcing wrong-template loop in the tail, not just distance.
  The paste-text arm cannot rut: its per-ask re-presentation is an anchor. A6 prices the
  rut rate; until it reports, deep-window attach is NOT default-ship.
- Production economics (grad §3): the volatile tier-3 block, riding between carts and
  history, re-evaluates block+history every turn. The carts are not the expensive part.

## The options, honest-shaped

(A) SESSION-SCOPING (posture, zero build). Windows open with carts attached and close
    before the tail. This is the owner's daily reality question: how deep do his windows
    actually run? His answer already came ("regularly past 10-20") - so scoping alone is
    not enough; it is hygiene, not the countermeasure.

(B) PULL-CADENCE (built already, zero new code). X-Strata-Carts-Pull re-presents a cart as
    one appended user turn - a client (me, the web UI) can pull every N turns. P6's shape:
    ~0.4 for ~10 turns per pull, cache-safe (pure append). The rut data adds a second
    reason to anchor: the anchor re-grounds cart identity, not just distance. Cost: one
    turn's tokens per anchor. This is the TOOL; what it lacks is a policy owner - the
    agent decides per window, no server machinery needed.

(C) HISTORY ROLL-UP (the P8 winner; the real build). The server does not own OpenAI-style
    history - the client sends it every turn - so a SERVER-side roll-up is architecturally
    backwards. The shape that fits our stack: the AGENT rolls its own scratchpad (every
    harness compacts its context; mine already does), and the store is the backing page:
    op=turns journals every turn verbatim (built, S-era), so a rolled-away turn is paged
    back with memory_search, never lost. vc's whole architecture, in our primitives:
    conversation = the record, prompt = the cache, shelves = the page device.
    Build needed: none for the mechanics; ONE policy + one measurement (a real deep window
    run with the harness compaction + carts attached, scored like P8's L arm).

(D) P10 - RECALL-BLOCK POSITION (the economics probe, queued tonight, may reorder S4b).
    Move the block from head (today) to tail (after history). Predicted from the grad
    eval-curves: history becomes cacheable again, per-ask cost goes FLAT (like arm B's
    1,426, likely below it), and recall position of the facts IMPROVES (right before the
    question - the strong tail arm of the U). Risks to measure: the one-system-message
    template law (the block must ride as a user-side merge, not a second system message),
    and whether block-at-tail changes answer style (the recall facts' influence rises with
    proximity - could help tier-3 or could crowd the persona). If P10 measures, the
    "carts cost 2K/ask" headline from graduation shrinks toward "carts cost ~0.5K/ask and
    the block was the bill" - and re-running graduation after P10 may flip NOT YET to
    GRADUATE without any attach change at all.

## Recommended sequence (owner's veto stands on every line)

1. A6 reports -> rut rate on the record.
2. P10 runs (queue behind A6 tonight if the engine is free; ~10 min) -> block-position
   economics measured on the same 30-gold geometry.
3. If P10 confirms: move the block (one function, one order test), re-run graduation
   (half-day including my sleep debt), and the gate gets its second bite.
4. C3 ratification (roll-up posture) then rides the compaction-policy measurement (C),
   which is a DAY of real-window use, not a bench - natural venue-day fare.

## What I will NOT do without you

- Move the block position (P10 measures it first; a persona-file edit mid-measurement
  would rotate the standing and muddy the before/after - the freeze law).
- Ship default-on attach anywhere (the gate says NOT YET; the owner's "few carts by hand"
  posture already covers the opt-in path).
- Pay the venue-day list (shelved by your word, 2026-10-25).
