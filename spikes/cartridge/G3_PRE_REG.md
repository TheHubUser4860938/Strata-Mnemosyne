# G3 pre-registration — the graft gate: does a COMPOSED cartridge recall as well as injected text, while paying no prefill?

Written 2026-10-25 ~11:20, BEFORE any G3 ask, countersigned in two stages (rubric + arms + gate
now; the gold rows appended in a dated addendum before the first ask, countersigned again — the
C4 pattern). Prior measurements it stands on, all banked: C4 Phase C (episode carts recall 1.000
single / 0.996 composed k=2..5, text-RIDING geometry: body re-sent as prompt tokens over restored
rows, cache-hit — prefill-free, NOT text-free); the 2026-10-25 mechanism probe and read-protocol
sweep (state-ONLY read on this GDN hybrid: 0/4 markers on all three question shapes; the model
senses prior context but cannot extract from it; same rows with body as text = 1.000); the S3
live boot (ledger, row zero, first real cart mam-test745 at 607 tok / 245.4 MB — C4's fit 0.1%
off; rotation law proven mid-probe; restore ~110 ms, hand-back 114 ms).

## The one question

**With the cart bodies COMPOSED once into the slot (standing bytes + selected bodies as one
stable prefix, saved as a session file), does conversation recall reach >= 0.9 x the same content
injected as a per-turn text block — while steady-state prompt-eval pays only the conversation's
own new tokens?** The compose is what the index line already promises: the line names the carts;
the compose makes them ride. Today's mechanics support arm A with orchestration alone (no engine
work); the state-only dream is arm C, reported, not gated.

## Arms (three carts ride every arm; selection is S4.x, not this gate)

- **A — COMPOSED (the ship-able arm).** Pre-compose one session file: standing bytes + the three
  bodies in ledger-name order + acks; restore it once per conversation; the server-side prompt
  then carries the same bytes at the same fixed position every turn (the bodies RIDE AS TEXT at
  zero compute via prefix cache — today's compose mechanism, exactly what C4 measured recall on).
  12-turn scripted conversations; questions at turns 3/6/9/12, probes interleaved.
- **B — TEXT-INJECTION control.** Same bodies as a per-turn block at the tier-3 position, no
  session file, re-evaluated every turn. The known upper bound and the token tax.
- **C — STATE-ONLY (research line).** A's restore, but the bodies' bytes are NOT re-sent
  (questions ride raw on the state, best shape from the 2026-10-25 sweep). Reported with its own
  3 passes; no gate; today's prior is ~0/4, and arm C gets a fair trial before that stands.

## Gold set, rubric, passes

- Three carts x 10 marker QAs (30 golds): `mam-test745` (lives); `c4-results` (a fresh ~700-tok
  excerpt of the banked C4 verdict numbers) and `merge-notes` (a fresh ~700-tok excerpt of the
  v0.2.4.2 + v0.2.5 merge record) minted for the run from committed text. Excerpts + gold rows
  land in the bench dir as the countersigned addendum BEFORE the first ask.
- `hit()` = exact marker match (numbers may shed commas/spacing; never a substring — the sweep's
  scar: "no" matched "knowledge"). Distractor pool = the other carts' golds, reported not mixed.
- 3 passes per arm per gold, **temp 0.8** (bench law), temp-0 sanity pass reported alongside, not
  gated. idk counted as its own bucket; abstentions never counted as leaks.

## The gate (pass = the graft ships for arm A)

1. **Recall**: A >= 0.9 x B, overall AND per-cart (slice before verdict — a per-cart miss under
   0.9x is a scar to adjudicate, not something to average away).
2. **Prefill-free**: steady-state prompt-eval (uncached tokens/turn) for A <= the conversation-only
   baseline + 5%; B must pay the bodies' tokens every turn (actuals reported, the tax made visible).
3. **Guards**: foreign-leak probe (a never-composed cart's golds asked against the compose: expect
   0/10, scar above 1/10); geometry check per turn (prompt tokens == standing + bodies + conv + q,
   else the row voids — C4's template); NO-ROTATION clause (persona files frozen for the run; a
   rotation mid-run is tagged and the affected arm rerun); wall-clock per turn reported (restore
   ~110 ms is the conversation-start cost, amortized — the number the owner's NVMe-wear class cares about).

## Venue and records

Live server (huihui box, engine 0.1.50, --kv int8 streamed, MTP spec-4), slot 0, probes interleaved
between the owner's turns; durable records to `/home/eugene/Strata-data/bench/g3/<tag>/` (JSONL
rows, summary, a dated Results addendum to this file). Never /tmp.

## Non-goals, pre-registered so they cannot become the headline later

Whether state-only CAN work on GDN hybrids (arm C reports; the mechanism question is S4.x, and
MAM's own numbers do not cover this architecture); selection law (which carts ride which
conversation — the call-number routing, all carts ride here); multi-conversation cache eviction
politics (slot_retain already guards the ledger's files); economics (C4 banked the fit; no
refit here).

## Countersign

- Clio signed 2026-10-25 (rubric fixed before the run; the sweep's classifier scar is in the rubric).
- Owner countersign: ____________________  date: ____________
- Gold addendum (appended before the first ask, both signatures required): pending.
