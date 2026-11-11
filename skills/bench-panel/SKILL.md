---
name: bench-panel
description: Measure a change on a frozen eval panel, with repeats.
---

# Bench panel

How to prove a change helped, on this box: fix the rubric, move one variable,
run the repeats, write the record where it survives. The panel is frozen on
purpose — a rubric that moves mid-run measures the rubric.

## When to use

- Changing retrieval, the shelf, the cartridge, the drafting stack, or the
  harness plugins, and you intend to say the change was a net positive.
- Re-running an existing panel after a merge, a re-index, or an engine bump.
- Anyone asks "is it better?" and the answer will be a number.

## Procedure

1. **Name the one variable.** Write down what you moved and what stays. Two
   changes at once is weather, not cause (the browse-pilot arc read as cause
   because it moved one knob per boot: 0.25 → 0.30 → 0.70).
2. **Freeze the instrument before the run**, and say which instrument. Panel,
   scoring script, repeat count, temperature. Fix the known quirks *between*
   runs, not inside one: comparability beats local correctness, and the scar
   stays visible.
3. **Run the suite that covers the touched surface, first and green:**

   ```sh
   cd ~/Projects/Strata-Mnemosyne && .venv/bin/python -m unittest discover -s serve -p 'test_*.py' \
     > ~/Strata-data/bench/p1/serve-suite-<what>-<date>.log 2>&1
   ```

   Narrow it while iterating: `.venv/bin/python -m unittest serve.test_memory -k PageControls 2>&1 | tail -12`.
   Syntax-check a big edit before the long run: `.venv/bin/python -m py_compile serve/memory.py serve/server.py`.
   The harness side is `node --test build/tests/` from `~/Projects/Clio`,
   grepped for `^ℹ (tests|pass|fail)` and `^✖ `.
4. **Run the panel with ≥3 repeats** at the temperature the work is used at
   (bench answers 1.0; probes and judges temp-0 style). Report the spread, not
   just the mean.
5. **Read the shape before the mean.** The mean is the last evidence, not the
   first: pilot v2's means said "no effect" while browsed rows went 8 of 8.
   Slice by arm, by class, by section — a quadrupled binding (1/12 → 4/12)
   hides inside a flat mean.
6. **Score binding and content separately.** On the founding panel, `PAPER`
   and `FILE` score which document the route chose, `CONTENT` scores whether
   the text is right. They disagree on purpose: the shelf routes to
   `hamilton_works`, which contains the same paper the gold file names.
7. **Write the record where it survives** — `~/Strata-data/bench/`, named
   `<what>-<date>[-<suffix>].log`. `/tmp` is parking, not storage.
8. **Report with provenance**: the number, the n, the log path, what was not
   tested. A number with no log path is a claim.

## Pitfalls

- Quote the runner from the repo's own docs (`python -m unittest discover -s
  serve`), because pytest reports subtests as failures and inflates the count —
  a suite that is green reads as 477 failures.
- Expect a constant offset between a local render and the boot (+42 tokens
  measured on the chat template), so *measure* the gap on the shape being
  scored: a difference of two boot-side renders cancels the constant out of
  sight, and a prediction from one render hides it.
- Treat small deltas on a 12-topic panel as noise (a fused-arm +0.003 MRR at
  n=12 was inside noise) — the panel's value is the *shape*, and its ceiling
  is how often the gold row is inside the top 8.
- Name the arm's ceiling when you report the arm: the LLM rerank scored flat
  because the gold row reached the top 8 on only 6 of 12 questions.
- Do not trust a field's name as its units: `carts.tokens` is the engine's
  save/restore count for the LAST operation, not the text's token count. Read
  what produces the number before quoting it.
- `GET /metrics` answers with **12** request rows by default
  (`serve/server.py:6470` `hist[::-1][:12]`) out of a ring that keeps 500
  (`:5549`) — ask `?requests=all`. On 2026-11-09 a 12-prompt drafting panel
  summed to three different acceptances (0.686, 0.700, 0.706) because the live
  session's own traffic slid panel rows out of the 12-row window; the engine
  log's per-request `drafts accepted X of Y` lines are the durable instrument.
  Compare `requests_kept` to the rows you summed, and say which you read.
- Re-measure the baseline after a merge: the suite count is a series
  (1,756 → 1,800 → 1,895 → 2,057), and an old number beside a new run reads as
  a regression that never happened.
- A trailing `&` swallows the `cd` into the backgrounded subshell, so the commit
  that follows a backgrounded suite runs in `~` and dies with "not a git
  repository" (cost three retries launching panels on 2026-11-08). Name the repo
  on every git call after a background launch: `git -C ~/Projects/<repo> …`.
- Score an external judge from its **item list, not its summary**: on the
  49-item Grok round (2026-11-08) two group headers were each one off their own
  lists in opposite directions — `temporal` headed 3/7 over 4 yes, `user` headed
  6/7 over 5 yes — and the errors cancelled, so the total read correct. Parse
  the per-item verdicts, recompute the groups, and report the disagreement.
- When you swap judges, **re-judge both arms under the new one before claiming
  an order**: on 2026-11-08 the local 3-repeat majority ranked the dive arm
  above knobs (+0.048) while Grok's repeat-1 packet ranked knobs above dive
  (+0.062) — and the judges agreed with each other (κ≈0.82–0.88), so the order
  is judge-dependent, not judge-noise. Means from different judges are not
  comparable; paired flips within one judge are.
- Before calling a run done, **count the run's own file** (`wc -l` + the
  harness process gone): on 2026-11-08 an arm was reported complete at
  "147/147" taken from the *previous* arm's count — the analysis divided by a
  constant, and the live file held 3 lines mid-run. A denominator is not a
  progress check.
- A metric **identical to the digit across arms** means the lever is inert, not
  that the arms agree. Three glossary arms (off, 0.25, 0.6) all read
  `row_coverage 0.698`, so the accuracy spread 0.435–0.497 was sampling on 147
  lines (1 SE ≈ 0.041) — the vote never fired (its loop read the map's keys
  backwards). Ablate the knob and assert its *proximate* metric moves; a golden
  test the fallback path can also satisfy is not evidence the feature is on.
