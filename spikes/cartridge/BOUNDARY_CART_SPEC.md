# Boundary-cart spec — the MAM idea, retuned for our hybrid (renamed 2026-10-30)

**The owner's ruling, verbatim:** *"I want to pursue the path that works on this model we can't copy his
work to the letter because he's using a model that is quite different to ours so name things the way it
works on our model. So take inspiration from but do not copy we need to take a different path and won't be
replicating his exact results due to architectural differences. So keep tuning so it works well."*

So: the line of work is the **boundary cart** — a partial state at a trunk boundary, mounted with zero
input embeddings, the layers above recomputed. `CUT3` stays only as the name of their cut (after block 3 of
80 on a dense model). Ours sits at **layer 12 of 48**, and the honest headline is **escaping the fixed
floor** (a cart costs 238 MB today whether it knows one sentence or seventeen hundred), not their 10x K/V
ratio, which a hybrid cannot chase. Two consequences of the swap, both measured: our row is *bigger* per
token (20,480 B bf16 against their 16,384) because the hyper-connection carries four streams; and this
engine reads a long prompt on more than one path, so a tap on one path covers 99 positions and calls it a
day — coverage, not the byte rate, is where the tuning work is.


Owner's decision, 2026-10-29: **"I want MAM cartridges otherwise what is the point of the
cartridges?"** — i.e. the actual CUT3 mechanism (partial state + recompute), not the whole-state
restore our graft does. This is Phase 1-3 of `spec-driven-development`; no code yet.

Skill used: `spec-driven-development` (spec before code). It changed the outcome once already: the
scope check turned "build MAM" into three separable capabilities, only one of which is the spike.

---

## Phase 0 — capability map (what "MAM cartridges" actually decomposes into)

| # | capability | do we have it? | where |
|---|---|---|---|
| C-1 | **capture** per-token hidden states at a layer boundary during prefill | **primitive exists**, research-only | `KvaTap` writes `R` entering layer `l` per chunk (`src/prefill/prefill.cpp:2842-2926`, fired `:5601-5604`); DFlash2 taps are production (`prefill.cpp:5601`, `include/strata/kernels/dflash2.hpp:96`) |
| C-2 | **mount** pre-computed rows at a boundary with zero input embeddings, run the layers above | **primitive exists**, multi-GPU only | `Prefill::set_stage` — "a stage that does not start at layer 0 reads each chunk's residual rows from the previous stage **instead of embedding the tokens**" (`include/strata/prefill/prefill.hpp:231-236`), consumed `prefill.cpp:3135-3227` |
| C-3 | **persist** those rows in the cart file | **no** | `put_payload` writes geometry, live+checkpoints, K/V only — no activation section (`src/core/conversation_file.cpp:682-708`) |
| C-4 | **mix per position** — cart positions take rows from the file, question positions take rows computed by the layers below | **no** (the gap) | `hand_in_` is all-or-nothing per stage today |
| C-5 | **router** — pick the cart by the model's own state | no, and no output path | engine→server protocol is tokens + counters only (`generate.cpp:16434,17189`); no `/v1/embeddings` in `serve/` |

**The spike is C-1 + C-2 + C-3 + C-4.** C-5 rides on it almost free (see "The router comes free").

## Why the cut maps onto our hybrid at all (this was the open risk; it is now closed)

MAM cuts "after block 3": H3 for every token plus the K/V of blocks 0-3, blocks 4-79 rebuilt
(Zenodo TEST815, saved in `~/Documents/Clio's_Research/scratch/`).

Our trunk is a hybrid, and the rule is `is_qsa_layer(g, l) = l % qsa_interval == qsa_interval - 1`
with `qsa_interval = 4` (`include/strata/core/geometry.hpp:75-77`, `:26`). So full attention runs at
**layers 3, 7, 11, … 47** — 12 of 48 — and layer 3 is our **first** attention layer.

**A boundary at 4 on our box is structurally the same cut as MAM's:** below it sit three recurrent
layers plus exactly one attention layer. The mechanism transfers; only the byte sizes differ.

## The storage math (arithmetic on compiled geometry constants — NOT yet measured)

`hc = 4`, `n_embd = 2560` (`geometry.hpp:23,49-50`) ⇒ the residual `R` is **10,240 floats/token =
20,480 B in bf16**. Per-layer K/V measured from our own cart: 19.5 MB / 13 sections / 1,369 tok ≈
**1,149 B/token/layer**. GDN running state ≈ 3.27 MB per layer, fixed size, position-independent.

A cart at boundary 4, bf16:

| part | T = 1,369 tok | T = 1,730 tok |
|---|---|---|
| rows at the boundary | 28.0 MB | 35.4 MB |
| K/V of the 1 QSA layer below (layer 3) | 1.6 MB | 2.0 MB |
| GDN state of the 3 recurrent layers below | 9.8 MB | 9.8 MB |
| PLE n-gram history | 0.4 MB | 0.4 MB |
| **total** | **≈ 39.8 MB** | **≈ 47.6 MB** |
| the same cart today (whole state) | 257 MB | 262.6 MB |

**About 6× smaller**, and the important part is *why*: today 117.7 MB of a cart is 36 fixed-size GDN
states; at boundary 4 only **3** of them are inside the cart (9.8 MB). That is the MAM 1/10 story
re-derived for our architecture, and it is what makes a **bank** of carts cheap.

## What CUT3 does *not* buy us (say it before the build, not after)

- **Not work-per-ask.** A mount re-runs layers 4-47 over every cart token on every read. Text-riding
  re-reads the same tokens through all 48 layers. So a mount costs ≈ 92% of a text-ride's prefill and
  ~nothing less — MAM admit the same ("no measured end-to-end speed advantage"; their own rebuild is
  2.42 s per cartridge, 4.85 s to append a second). Our graft's 70 ms restore stays the cheap arm.
- **The prize is different**: a ~6× smaller persisted bank, no cart bytes on the wire or in the prompt,
  the below-boundary state kept out of the box's VRAM, and a routing key for free.
- **The scientific question is the whole reason to build it**: does recompute-on-read make the state
  *carry knowledge* where our restore measured net +0.000 / +0.067 / +0.000 (P4, n=30, ±0.07)? The
  candidate explanation is CacheBlend's finding that cached K/V reused **without** recomputation loses
  quality — which is exactly the difference between their mount and ours.

## Phase 1 — spec

**Objective.** One exchange, one cart, mounted at a layer boundary with no cart text in the prompt,
answering golds the model cannot guess — and a measurement that separates *carry knowledge* from
*save work*.

**The mechanism as we will build it (boundary N = 4 to start).**
1. **Mint** (host-side, once): prefill the source text; tap `R` at boundary N for every source token;
   snapshot the below-boundary state (GDN layers 0-2, the K/V of QSA layer 3, PLE history). File ≈ 40 MB.
2. **Mount**: layers 0-3 run on the **question** tokens only; at boundary N the stream is
   `[cart rows ; question rows]`; layers 4-47 run over all of it; decode continues normally.
   Positions advance as usual, so the cart still occupies real positions (it frees the *wire*, not the window).
3. **Read protocol** matters and is pre-registered: MAM's READ is a *query against a memory*, not a
   continuation of a dialogue. Our journal already names this as an untested cause of arm C's weakness.

**Boundaries / non-goals for the spike.**
- No composition (appending a second cart, RoPE re-phasing) — phase 3.
- No router — phase 2, but the rows make it possible (below).
- No `Linear` projector (KVA declares it "not implemented in this step", `include/strata/prefill/kva.hpp:16`);
  we mount the **real** rows, bf16. Storing a mean of the 4 hc streams instead of all 4 would drop
  information `gr_read` consumes (`include/strata/core/layer.hpp:459-462`) — noted as a lever, not a default.
- Opt-in, default path byte-identical (the fork's law). New checks must be shown able to fail.
- Known scar to design around: **the PLE**. Layers below the boundary do not run for cart positions, so
  the PLE n-gram history has to be stored or explicitly excluded — this is the same "row-math /
  history-free prompt shape" blocker the journal already names.

## Phase 2 — plan (change set, most → least invasive, from the static read)

1. **Capture tap** beside the KVA tap in `Prefill::run_impl`'s layer loop (`prefill.cpp:3613-3705`),
   reusing `KvaTap`'s write/read plumbing. Low.
2. **Per-position mount** (C-4): generalise `hand_in_` from "the whole stage takes rows from a peer"
   to "positions `[0, T)` take rows from the cart, the rest are embedded". The `hand_in_ == nullptr`
   special-cases need review (`prefill.cpp:2507, 2938, 3017, 3020, 3082, 3101, 3137`). Medium-low.
3. **File section** (C-3): an optional activations block in `SavedConversation` + `put_payload`/
   `get_payload` (`conversation_file.cpp:682,758`), magic `STRSESS\x01` v1 → flags or version bump,
   `SessionReadLimits` and the size estimate extended, read fail-closed. Medium.
4. **Serve verb** beside the graft: `MOUNT <path>` + `X-Strata-Carts-Boundary` (or reuse
   `X-Strata-Carts-Graft` with a mode). Precedent is fresh — the graft taught us the FIFO shape and
   the 120 s wait floor. Medium.
5. **Kernels / graphs: no change.** Prefill launches straight from `R`, and the captured decode graphs
   read `bb.R` in place (`src/core/session.cpp:200-260`). Low.

**Order:** 1 → measure capture cost & fidelity → 3 → 2 → 4 → bench. One variable per boot.

## Phase 3 — tasks with acceptance criteria

| task | done when |
|---|---|
T1 capture tap | a cart-sized prefill writes rows at boundary 4; bytes on disk == T × 20,480 ±0; the run's answers are unchanged with the tap off vs on (fidelity of the tap itself) |
T2 fidelity probe | mounting the captured rows reproduces the full-prefill answer for the same prompt (same gold, temp 0); a wrong-boundary mount must NOT (falsification) |
T3 file section | a cart file round-trips rows; a truncated file is refused, not half-read; the old v1 reader refuses a v2 file loudly |
T4 serve verb | one request with no cart text in the prompt answers a novel gold; the same request without the mount abstains |
T5 bench (pre-registered) | see below |

## The measurement contract (fixed before the run)

Novel golds (never in the persona text — the P2 persona-echo law), temp 1.0 per the owner's daily
rule, ≥3 repeats, two-sided per MAM's evidence control and our own ablation run 3:

- **Knowledge**: WITH the mount answers, WITHOUT abstains. This is the number that decides whether
  CUT3 is worth more than our restore. Target: the two-sided property MAM showed (6/6 abstain when the
  source is removed) and that our text arm already showed at 2/2 golds.
- **Work avoided**: prompt tokens and wall-clock per ask, against two arms we already price —
  text-riding (~1,150 prompt tok/ask; 15,068 vs 13,914 measured today) and graft restore (70 ms).
- **Fidelity**: mounted-answer vs full-prefill-answer agreement (T2), reported first — if this is bad
  nothing else is interpretable.
- Verdict rule: **CUT3 replaces the graft as the cart story only if knowledge ≥ the text arm at
  comparable or lower cost.** Otherwise it is a storage/bank win and we say so plainly.

## The router comes free (why the boundary is also the picker)

If carts persist rows at boundary N, the router needs only the question's rows at the same boundary —
one short prefill — then cosine against one mean-centred direction per cart. That is MAM's router
exactly (their numbers: top-2 16/16 including paraphrases, decoy-in-top-2 0/16), and it is the piece
that answers the owner's "pull as many as I want". Today the engine returns only tokens and counters
(`generate.cpp:16434,17189`) and `serve/` has no `/v1/embeddings`, so C-5 needs one output path — but
the *representation* is a by-product of C-1/C-3.

## Decisions — answered by the owner on 2026-10-29

1. **Boundary → TUNED, N = 12.** His reason, verbatim: *"we running a different model than what he was
   testing so go with tuned."* That is the better argument: a cut copied from a dense 80-layer model is
   faithful to their paper, not to our trunk. At 12 the cart keeps nine GDN states and the K/V of three
   attention layers (3, 7, 11) and re-runs 36 of 48 layers per read instead of 44 of 48. The re-derived
   size for a 1,730-token body: rows 35.4 MB + K/V 3 layers ~6 MB + 9 GDN states ~29.4 MB + PLE 0.4 MB
   ≈ **71 MB against 262.6 MB today — about 3.7× smaller**. Still a bank win, half of what N = 4 would
   give, paid for with a third less recompute per read. Both numbers are pinned in the test (C5, C6).
2. **Sequencing → build first, restart once.** His words: *"just let me know when everything is ready
   then I'll do the restart for you."* So the boot must carry the graft control **and** the first CUT3
   number, which is why the probe is built to skip rather than fail (below).
3. **Rows dtype**: bf16 stays the default (20,480 B/token); fp32 doubles the bank for a fidelity margin
   nobody has asked for. Measure the drift at T2.

## T1 is BUILT (2026-10-29) — `STRATA_CUT3_CAPTURE`, and why it skips instead of failing

The capture is one new knob in `Prefill::run_impl` at the same seam KVA already hooks: the rows of `R`
**entering** layer 12, per chunk, in position order, written by the existing `KvaTap` plumbing to
`<dir>/L12.bin` (bf16). Decision half in `include/strata/prefill/cut3.hpp` (pure, no device), tested by
`src/prefill/cut3_test.cpp` — **29 checks**, and three of them were **falsified on purpose** before the
run was believed: boundary 12→13, `row_bytes ×2`, and dropping the in-order rule each produced the named
`FAIL` and the tree went green again on restore.

**Skip, never fail** is the design point that makes one restart enough. `STRATA_KVA_CAPTURE` treats an
out-of-order position as an error, so it can only ever run alone on a quiet box. This probe declines the
ordinary traffic of a cartridge box instead — a continuation (`pos0 != 0`), a chat turn carrying the
standing text (~13.9k tokens, above the default 4,096 ceiling), a layer split, a prompt with pictures —
and a failed write stops the capture without touching the request. So with the knob set, one boot gives:

* the **graft pure test** (the control: restore, no text, prompt ~26 tokens), and
* the **first CUT3 number**: the rows of the `mam-cut3` body at boundary 12, whose size either matches
  `T × 20,480 B` or it does not, plus the cost of capturing them.

Launch line (the box runs on code defaults — its environment carries no `STRATA_*` today, verified from
`/proc/<server>/environ`):

```sh
STRATA_CUT3_CAPTURE=/home/eugene/Strata-data/bench/p1/cut3_rows \
  .venv/bin/python serve/server.py --engine strata --config strata-huihui-ud-q4_k_xl.json --port 8005 --open
```

Unset, C1 guarantees nothing runs and nothing prints — the default path stays byte-identical, which is
the fork's law. The durable shape of this knob is the box config rather than the environment; that move
is deliberately left to T2, so T1 changes one variable and not two.
