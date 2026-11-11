---
name: shelf-ops
description: Work the memory store: browse, write, shelve, embed.
---

# Shelf operations

The store is a Postgres-backed library with shelves (call numbers), a harvest
that writes on its own schedule, and two surfaces: the HTTP `/memory` API and
`memory_search`. Most shelf work fails on the seams between them, so the
procedure is: read the live shape, then write to an identity.

## When to use

- Answering from memory: searching, browsing a shelf, reading the map.
- Writing: remember, correct, classify, forget, purge, link.
- Shelving work: the reshelving clerk, the cutters, the embed pass, the
  document index, the curation sweep.

## Procedure

1. **Browse in the three verbs.** Ask with words (`q`), ask for the map
   (`catalog:true` — shelf names with row counts, read it when you do not
   know where to look), name a shelf (`class` alone walks it newest-first).
   Narrow with class prefixes and `since`/`until`. `class: "OPS"` is a
   subtree, not an exact mark.
2. **Treat `found: 0` as one look, not a search.** Try other words and another
   shelf, then say plainly that you found nothing. Rows arrive with `when`,
   `confidence`, `hits`, and a `rel` that is the search's own belief — about 1
   for a top pick, about 0.1 for a polite maybe. Rows fetched at low `rel`
   deserve a hard look before you repeat them.
3. **Name the target from a live read before you write.** "The store" is not an
   identity: fact 10982 landed in the venue because the address had changed,
   and the 09:42 sweep read prod and wrote venue on colliding ids.
4. **Pick the right removal verb.** `invalidate` takes a row out of recall and
   keeps the chain; `forget` is a tombstone (`invalid_at` + a `forgotten`
   record in provenance) and drops the vector; `purge` is the hard DELETE,
   legal only with a reason, and it records the victim in the `purges` ledger
   (sha256 + a 200-char head) before it kills. Never erase without annotating.
5. **Split facts from documents when you count.** `stats()` reports `facts`
   (source not like `doc-index%`) and `doc_chunks` separately — 2,056 facts
   beside 33,382 chunks. A count that mixes them makes 1,318 memories read as
   36k.
6. **Re-shelving is a clerk call, not a rename.** `Docs.set_class` +
   `Docs.cutters` move a book into its own drawer with one UPDATE and the
   vectors intact (141 book drawers, 229 s for the whole corpus pass). The
   clerk's 3-row bar: a cutter earns a drawer at 3 rows, smaller ones roll up
   into the family.
7. **The embed pass is resumable and batch-bound.** `m4_embed --threads 4
   --batch 16` measured 2.1 rows/s at ~8 GB; batch 64 with 8 threads fell to
   1.2 rows/s at 25.95 GB RSS. Batch size is the knob, not the thread count —
   memory traffic is the bottleneck.
8. **Re-index with `--force` when only the mode changed.** The cut mode lives
   outside the stat key, so an untouched folder keeps its old rows without it.
9. **Prove it on the panel after a shelf change**, not on the row count
   (see `bench-panel`): binding (`PAPER`/`FILE`) and text (`CONTENT`) are
   scored apart, and a re-cut that quadruples binding (1/12 → 4/12) leaves the
   mean almost still.

## Weekly maintenance

A shelf label is a guess about meaning, so the taxonomy needs a keeper. Run the pass weekly,
in a window when the engine is quiet: steps 3 and 4 ask the served model, and the harvest
wants 240 s of silence for itself. `tools/tidy_cron.sh` is the entry point and carries the
install notes; this box runs it Saturday 01:00 as the systemd user units
`~/.config/systemd/user/strata-tidy.{service,timer}` with `Persistent=true`, so a Saturday
with the machine off runs at the next boot. A whole pass measured 24 s.

1. **Read the map** — `memory_search catalog:true`, or `GET /memory?op=stats`. Note the wild
   count, the shelf count, the average rows per shelf and the singletons. Measured arc:
   583 wild rows (26% of 2,226) on 2026-11-02, 63 (2.8%) on 107 shelves after the passes
   below. The number is the run's own record, so write it down.
2. **Name the shelves the keyword map cannot.** `tools/m4_shelves.py --min 5` clusters the
   wild rows by cosine over the vectors the store already carries and prints the clusters
   big enough to be a subject, with their rarest shared words and exemplars. New cutters
   come from evidence like this, not from more keywords.
3. **File the wild rows.** `tools/m4_reshelve.py --class WILD --apply` asks the served model
   to place each row against the store's own shelf list; it answers existing shelves, a new
   `FAMILY/CUTTER`, or WILD. Read the review log it writes — a false shelf hides a fact, a
   wild shelf only waits.
4. **Trim the tail.** `tools/m4_shelftidy.py --tops --roll --apply` maps the tops the clerk
   invented onto a family (`FLUOR → BIO/FLUOR`) and rolls every cutter under the 3-row bar
   up into it. Sorting is two rules: too wild and too fine.
5. **Refresh the labels.** `tools/m4_catalog.py --apply --quiet` rewrites the MEM/CAT index
   rows (the `SHELF - words` contract) so a question can match a drawer whose name says
   nothing. Any new family added this week earns a label here.
6. **Then re-measure** on the frozen panel (see `bench-panel`): shelving moves routing, and
   routing is scored, not counted.

Keep the family list short — 16 families covered 2,100 facts on 107 shelves. A cutter earns
its drawer at 3 rows; below that it rolls up.

## Pitfalls

- Do not expect one shape from the API: `op:"carts"` answers BARE
  `{ok, carts}` with no `result` wrapper, and reading `.get("result", {})`
  there reports carts missing. `op:"search"` reads `q` — a body that says
  `query` is an empty search, and returns an arbitrary ranking.
- `remember()` refuses rows over 4,000 characters, so a full-text index is
  necessarily chunked and a document's rank is its best chunk's rank.
- The harvest is gated four ways — a systemd user timer (not a crontab), the
  tick runs only at `pressure=1` or `pending>5`, `--batches 2`, and `--sweep`
  waits for 240 s of total engine silence. Median said→written is 6.92 h, so
  "it is not on the shelf yet" is normal, not a bug. Use `op=curate` to spend
  the wait on purpose.
- The clerk fires only on the `or` branch, so a healthy-looking tick proves
  nothing about it — check the marks moved, not the log's tone (the queue was
  frozen for 13 ticks re-extracting the same turns with zero marks).
- Budget is the interface for a small model's format: 220 tokens returns an
  empty reply (all thinking), 700 drops the `FILE:` section. ANSWER FIRST,
  THINK AFTER — 1200-1400 tokens answers, then justifies.
- A shelf label is a guess about meaning, so prefer a false shelf to a wild
  one in review order: a false shelf HIDES a fact, a wild shelf only waits.
- The census and the clerk read different row sets: `m4_shelves` counts every
  scope, `m4_reshelve` walks facts and skips `doc-%`. A pass that prints
  "1 wild row" and "queue 0 rows" has found a document chunk — shelve it by
  hand with `op=classify` (the 2026-11-11 pass found a `docs-perf` fixture,
  row 136438 → `DOC/RUSTP`) and the census reads 0.
