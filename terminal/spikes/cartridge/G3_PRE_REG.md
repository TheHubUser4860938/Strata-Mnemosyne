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
- Owner countersign: verbal "Go", 2026-10-25 (stamped by Clio at the run's start).  date: 2026-10-25
- Gold addendum (appended before the first ask, both signatures required): appended 2026-10-25,
  countersigned with the rubric by the same verbal "Go" (the two-stage seal closed at once).

## Gold addendum (2026-10-25) - three carts minted live, thirty marker QAs

The carts were minted against the running server (op=mint, fresh, file_exists true):
`mam-test745` 607 tok / 245.4 MB, `c4-results` 600 tok / 245.3 MB, `merge-notes` 462 tok /
243.2 MB - and C4's fit (236.1 MB + 15.6 KB/tok) predicted 245.6 / 245.2 / 243.1: three
unscripted carts, all within 0.1%. The excerpts are authored from the banked records cited in
their `uri` fields (verdict file / journal), not verbatim document slices - provenance named so
a gold dispute has somewhere to go. `hit()` per the rubric: exact marker, commas/spacing free,
NEVER substring.

**mam-test745** (MAM Silicon Hippocampus reference, TEST745):

| # | ask | marker |
|---|---|---|
| 1 | How many physical cartridges did TEST745 build? | 11 (eleven) |
| 2 | How many body tokens does cartridge C01 carry? | 761 |
| 3 | What GPU ran TEST745? | A100 |
| 4 | Is synthesis between cartridges direct tensor fusion? | text-mediated / no |
| 5 | Independent post-run cartridge verification score? | 11/11 |
| 6 | How many text-mediated review rounds ran? | 8 (eight) |
| 7 | Human expert grading of the blind answers? | pending |
| 8 | Who is the researcher (name)? | Akbaş / Akbas |
| 9 | Which sealed master was forged before reading the final report? | C11 |
| 10 | What indexing answered selection prior art (TEST610/642)? | FAISS (or PCA128) |

**c4-results** (C4 verdict, tag 215424):

| # | ask | marker |
|---|---|---|
| 1 | Ladder mean recall at the 25-fact rung? | 1.000 |
| 2 | Ladder mean recall at the 500-fact rung? | 0.916 |
| 3 | Ladder mean recall at the 1000-fact rung? | 0.809 |
| 4 | What did the row-16 contract miss answer, where gold asked D56? | Y51 |
| 5 | Distractor answers at the 1000-fact rung? | 96 |
| 6 | The leak baseline declared at the 100-fact rung? | 0.06 |
| 7 | Between which rungs was the ceiling declared? | 100 and 500 |
| 8 | Composed recall at k=5? | 0.996 |
| 9 | The fixed MB cost per state file (the fit's intercept)? | 236.1 |
| 10 | The marginal cost per standing token? | 15.6 KB |

**merge-notes** (upstream v0.2.4.2 + v0.2.5):

| # | ask | marker |
|---|---|---|
| 1 | Which upstream version was merged on 2026-10-25? | 0.2.5 |
| 2 | The upstream merge commit hash for v0.2.5? | 8c19ef9a |
| 3 | How many serve/ files did v0.2.5 touch? | zero |
| 4 | Engine version after the rebuild from the fork's tree? | 0.1.50 |
| 5 | The BUILD.json src hash recorded? | 5944ca5d |
| 6 | The third victim of the pack-script rename? | update.sh |
| 7 | The commit that fixed the README version caption? | f77702da |
| 8 | The boot time of the green post-merge audit? | 07:55 |
| 9 | Which version was merged first, by tag, on 2026-10-24? | 0.2.4.2 |
| 10 | Which branch carries all of this? | memory-core |

Distractor discipline per the rubric: each cart's ten golds are asked only against conversations
where its own compose rides; the other carts' markers are the distractor pool (a marker from the
pool counts as distractor, never as gold). Control set (arm-A foreign probe): the `merge-notes`
gold 3 ("zero") is asked against a compose that EXCLUDES merge-notes - expected abstain, scar if
it answers.

- Golds drafted by Clio 2026-10-25; owner countersign of THIS table + the rubric above = the
  run's two-stage seal: verbal "Go", 2026-10-25 (stamped by Clio at the run's start).

## Results (dated addendum, appended 2026-10-25 after the run; rows: bench/g3/g3_122759/, log: bench/g3/full_run_1227.log)

Run: 3 passes x 30 golds x 3 arms + 3 control asks = 273 rows; temp 0.8 (bench law),
X-Strata-Memory-Block: off, tool_choice none, max_tokens 64; standing MEM-CRG-1ae6aa29.bin held
the whole run (the no-rotation guard was wired and never fired).

**VERDICT: GATE 3 PASS. The graft ships on the composed text-riding arm (A).**

1. RECALL, as scored by the frozen scorer: A 0.900, B 0.933, C 0.256 (n=90 each).
   Gate A >= 0.9 x B: overall 0.964; per-cart c4 0.926, mam 1.000, merge 0.964. All >= 0.9.
2. PREFILL-FREE: median eval/ask A 37 tok, C 41 tok (the question-only baseline), B 1,512 tok.
   A rides at the question's own tokens (band 27-85); B pays the bodies every turn. Clause met.
3. FOREIGN CONTROL: merge-notes' "zero" asked against a compose that excludes it answered
   distractor / idk / distractor - never gold. No leak; the misses confabulate numbers
   ("touched 38 serve/ files"), the honest shape of a composed-prefix guess.

Scars and amendments, in order of discovery. Frozen-instrument law: the scorer was NOT touched
mid-run; both arms wore the same scorer, so the ratio stands; the correction is reported beside
the raw, the scar stays visible.

- POST-RUN: the digit/version lookahead (?![\d.]) rejected sentence-final periods - "96.",
  "0.1.50.", "0.996." counted "other". 6 of A's 9 misses and 3 of B's 6 were this bug; the rest
  are genuine temp-0.8 early stops ("Must", "The", "0"). Corrected scorer (lookahead (?!\d)):
  A 0.967, B 0.967, C 0.278; gate 1.000 overall AND per-cart. Verdict identical under both.
- POST-RUN: B's conversation-0 first ask re-evaluated the WHOLE prompt (exactly 8,057 tok) in all
  three passes - deterministic, correctness intact (all three answered gold). A conversation-start
  cost after restore, not steady state; the medians above are the tax claim.
- PRE-RUN (runner code, logged against the signed rubric): tool_choice none - smoke caught the
  mounted search tool answering state-only asks (the first control cited store fact 5818: the
  research arm was reading the store, not its state); m3 gold variants expanded ("none",
  "no serve"); refusal-position rule (a refusal opening the answer abstains even if a marker
  arrives later); numeric equivalence for numeric markers ("1.00" is the gold 1.000, "18" is not
  the gold 8); max_tokens 48->64 after smoke truncation.
- Compose rebuilds cost 7 eval tok: a restore does not truncate the slot tail and identical LEAD
  bytes prefix-match the retained rows. Per-ask alignment is verified by A's eval band (27-85).

ARM C, the research line (reported, not gated): the state-only read is NOT dead on this hybrid -
0.278 corrected, with a cart-driven spread (merge 0.433, c4 0.300, mam 0.100) and 47% honest idk.
The morning probe's 0/4 was real but pessimistic at n=90. Cartridge CONTENT, not question shape,
drives the spread - S4.x research territory (seed/read shape, KV_ROT, engine-side anchors).

Signed post-run: Clio 2026-10-25; owner countersign of THIS addendum: verbal "Go", 2026-10-25
(stamped by Clio at her next turn, same day).
