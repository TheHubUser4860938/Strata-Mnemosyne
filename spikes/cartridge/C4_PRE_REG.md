# C4 pre-registration — the bank-capacity probe: how big may a cartridge grow before it stops being a cartridge?

Written 2026-10-24 morning, BEFORE any C4 ask, on the heels of the venue day that supplied its
instruments (a durable 500-question harness, a shelved router-live store, and the demote numbers).
C2 (3+3 swap purity), C3 (100/100 recall at the 100-fact bank, 600/600 across two eras) and C3-v3
(nonce leak probe at 103+100, 36/36 rides exact) stand as recorded. Their shared verdict: NO
interference ceiling found AT 100. The roadmap call of 2026-10-11 marked the open driver exactly:
"capacity beyond ~100 (1,000-fact bank ~35k tok fits 393k - open C4) + multi-domain selection."
C4 is that open. **The ceiling is unknown - that is the point.**

## The one question

**Does standing recall hold as the bank grows 100 -> 500 -> 1,000 facts, and what does each rung
cost?** C3 proved 100 is clean; the engine can carry 35k standing tokens in its 393k context with
room to spare; whether the MODEL still answers from a 1,000-fact bank as faithfully as from a
100-fact one is a measurement, not a hope. Three secondary questions ride along, pre-registered so
they cannot quietly become the headline later:

1. **Cost curve**: per-answer latency and tokens at each rung (the bank rides EVERY prompt - slot 2
   is permanent); and the one-time re-seed/install cost per conversation start as the bank grows.
2. **Leak curve** (c3v3 template at scale): does a swap between two big nonce banks stay pure
   (previous bank unreachable), or does interference appear with volume?
3. **Displacement**: the standing text currently caps at 12,000 chars; a 1,000-fact bank needs
   ~150,000. C4 runs with the cap raised by CONFIG, and records whether the bigger standing text
   crowds the tier-3 recall block out of the prompt budget (it should not: 48k block + 35k standing
   against 393k context - but "should not" is what the confound clause is for).

## Venue (fixed; the C-series shape, unchanged)

- Production engine (huihui UD-Q4_K_XL, 393k ctx), channel off, **temp 0.8** (user-measurement law:
  0.8/1.0, never 0, >=3 repeats - C3's own venue agrees), memory MUTED (the bank answers; tier-3
  recall stands aside), fresh conversation per probe family, max_tokens 24.
- Bank install rides the cartridge plumbing (c1): save/restore files via the live slot mechanism;
  banks are scratch stores under Strata-data/bench/c4/, never production.
- **Rungs**: 100 (control - C3's known-clean number, re-measured tonight's era for comparability),
  500, 1,000. Same generated nonce families per rung (zero-prior markers, idk-proven cold BEFORE
  install, as Gate-1 did), same QA probe set (one ask per fact, cued by its marker pair).

## Instrument and gates (fixed before the run)

- **Gate per rung**: per-fact recall >= 95% averaged over 3 passes, scored by exact-marker match
  (nonce golds need no judge); a rung FAILS below 95% and the ceiling is declared between the last
  passing rung and the first failing one.
- **Leak gate**: foreign-bank asks answered correctly <= the 100-rung's observed leak rate (c3v3's
  zero-leak precedent; binomial allowance stated at run time).
- **Cost ledger**: per-answer latency and tokens at each rung. Stated precisely so nobody reads it
  as re-prefill: the cartridge is PREFILL-FREE, not free - the bank occupies CONTEXT POSITIONS on
  every request, every decoded token ATTENDS over the standing KV, and a COLD cache or moved text
  pays the SEED once. The ledger measures exactly this resident-prefix price (MAM's design parks
  its bank OUTSIDE the window and injects only a selection per ask - whether our resident price
  bends badly with size is one of the numbers C5 will weigh for that path-B argument); and the
  one-time re-seed/install cost per conversation start as the bank grows. Reported, not
  gated - this probe's product is the CURVE, not a verdict.
- **Cold control**: every probe family idk-proven blind first; any fact with a cold hit is replaced
  before install (Gate-1 law, non-negotiable - priors are what voided C3-v2).

## Honest limits (said before, not after)

- Nonce banks measure MECHANISM capacity, not semantic-domain capacity: real 1,000-fact banks are
  related facts and will interfere more than unrelated nonces (the multi-domain selection driver
  from 2026-10-11 stays open for C5's bank-selection question).
- 500 and 1,000 are chosen rungs, not a search; a failure at 500 makes 1,000 moot and a pass at
  1,000 leaves the true ceiling above it (the next rung, if earned, is C4-v2's to pick).
- The 12k-char cap raise is CONFIG for the probe only; production keeps its small standing set
  until C4's cost curve says otherwise (the small budget loses standing status, not knowledge).

## Sign-off

Owner ratifies (or edits) the bands above; c4_run.py follows the c3v3_run.py pattern after
sign-off; the engine is shared, so the run schedule is his call, not this file's.

**SIGNED 2026-10-24 (evening), owner in-session: "Okay I sign off on all of these."**
C4's runner is still to be built - C5 runs first on the same signed basis; the pen precedes
the ask, the runner follows the pen.
(Both halves of that line later that night: C5 ran, and c4_run.py was built per this contract
and PROVEN at smoke rung-25 - all green, save 214 ms / restore 123 ms at 253 MB.)

## Amendment - the episode ruling (appended 2026-10-24 late night, AWAITING countersign; the sections above stand untouched)

The owner's course-correction, before the ladder runs, doctrine in his words: cartridges are not
for stuffing as much data in as possible - that is not how they are meant to be used. They store
data so the model's knowledge **expands locally**: *"you browse a web page and then the data you
learn from that web fetch is turned into a cartridge; now you never have to waste time making that
web fetch again, as you can just load that cartridge and you don't have to pay the token tax of
making the tool call and reading the web page."* The shelf holds the same doctrine since
2026-10-22 (shelving system for cartridges, no retraining, no LoRA). The unit of use is therefore
the **episode cart** - one experience, one cartridge, roughly web-page sized (~25 facts, ~1k
tokens) - and MANY of them, minted as things are learned, not one big bank.

What survives the ruling: the signed rungs and every gate - the capacity envelope is still worth
knowing before minting thousands, and a ceiling between rungs is a real answer. What changes is
what the night must produce: not only *"where does a single cart stop being faithful"* but *"what
does ONE episode cart cost, and how many may coexist"* - the unit economics the usage actually
runs on. Three amendments, gates/scorer/cold-control/venue/repeat law untouched:

- **A. Rung-25 joins the ladder as the first rung** (episode scale). The nested-rung law from C5's
  amendment applies: a bigger rung EXTENDS the encode, acks replay byte-exact. Smoke3's 25/25 is a
  preview, not a result - the ladder re-measures 25 with 3 repeats inside the nested sequence.
  Ladder: **25 -> 100 -> 500 -> 1,000**.
- **B. Phase C - unit economics** (reported, never gated, beside the cost ledger): mint 5 separate
  episode carts (25-fact nonce families, distinct, each idk-proven cold); per cart report state-file
  bytes with the FIXED-vs-MARGINAL split against cart tokens (the smoke's 25-facts-at-253 MB against
  the standing cart's 5.6k-tokens-at-326 MB says the fixed component is real and big - this names
  it), save ms, restore ms. Then attach carts 2..5 in sequence to ONE standing prefix: recall gate
  at each attach size (same >=95% exact-marker law), per-answer latency and tokens against the
  one-cart baseline (the MULTI-CART resident-prefix curve - the number the RAM arithmetic needs),
  plus one leak arm: an un-attached foreign episode stays unreachable.
- **C. Verdict clause extended by one sentence:** beside the ceiling declaration (between last
  passing and first failing rung, as signed), the night reports the episode band's health (does 25
  pass clean?) and a **carts-per-box estimate with the arithmetic visible**: N ≈ (share of the
  14 GiB conversation cache) / (fixed + marginal x tokens-per-episode), from the measured parts.

S3 note, no build tonight: the mint verb's SOURCES widen from store rows to EPISODE TEXT (a fetched
page, a read document) - a cartridge mints what was learned from one experience; the attach index
line carries the episode's identity ("page X, fetched 2026-10-24") and that line is what replaces
the re-fetch. Grok's manifest takes this as one more shape of `sources`, no interface break.

Runner note: c4_run.py exists and is smoke-proven; rung-25 is a config line (smoke used it),
Phase C is new (~60 lines, same plumbing, same guards). Owner's countersign (one word) makes the
amendment part of the contract before the next quiet-night run.
