#!/usr/bin/env bash
# strata-graph-update (2026-11-17, the owner's freshness order): the code graphs answer
# questions about TODAY's tree, not last week's. `graphify update` re-extracts only files
# whose content changed, with tree-sitter - no LLM for code, seconds to a couple of minutes,
# nothing leaves the box. An update never shrinks a graph silently: graphify refuses to
# overwrite when the rebuild has fewer nodes (that guard is left on, by design).
#
# One entry per graphed repo, run from the directory that OWNS its graphify-out/.
# To add a project: run `graphify extract <path>` once, then add its directory below.
# opencode-custom was extracted --code-only (2026-11-18): its 201 doc/paper files are skill
# prose, and a code-only graph needs no semantic key, so `update` runs here unattended.
# Log: ~/Strata-data/bench/p1/graph-update.log ; timer: strata-graph.timer (user unit)
set -u
GF=/home/eugene/.venvs/graphify/bin/graphify
LOG=/home/eugene/Strata-data/bench/p1/graph-update.log
say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

for d in /home/eugene/Projects/Strata-Mnemosyne \
         /home/eugene/Projects/monitor-fw \
         /home/eugene/Projects/opencode-custom; do
  [ -d "$d/graphify-out" ] || { say "skip (no graph): $d"; continue; }
  say "update $d"
  ( cd "$d" && nice -n 10 "$GF" update . ) >> "$LOG" 2>&1 \
    && say "ok $d" || say "FAIL $d"
done
say "graph update pass complete"
