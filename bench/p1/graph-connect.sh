#!/usr/bin/env bash
# The connect queue (2026-11-16, the owner's morning-after step). Run AFTER the reboot:
#
#   1. FOLD first — merged rows mean fewer rows to graph and composite nodes mean cleaner
#      concepts. The fold writes through op=correct, so the supersession chain survives.
#   2. Retire the session lane (facts true for one afternoon, older than 30 days).
#   3. COVER — drain the graph over every row no node cites yet (10 facts a file, 6 files
#      a chunk; loops until a pass adds nothing new, cap 12 passes; re-run it any number
#      of days and it picks up the queue where it stopped).
#   3. BRIDGE last — one cheap pass over the graph's own communities, wiring edges between
#      the islands. Wide is not walkable; the recall arm spends its votes along edges.
#
# One job at a time: four concurrent chunks on one 4090 is what produced the timeouts.
# Progress: /home/eugene/Strata-data/memory-eval/strata-graphify/progress.json
# Log:      /tmp/opencode/gf-connect.log
set -u
cd /home/eugene/Projects/Strata-Mnemosyne || exit 1
LOG=/tmp/opencode/gf-connect.log
say() { echo "[$(date '+%m-%d %H:%M')] $*" >> "$LOG"; }

say "fold start (limit 40, min-cos 0.82)"
PYTHONPATH=. .venv/bin/python tools/m4_fold.py --limit 40 --min-cos 0.82 >> "$LOG" 2>&1

say "session retire start (30 days)"
PYTHONPATH=. .venv/bin/python tools/m4_fold.py --session-days 30 --limit 200 >> "$LOG" 2>&1

say "cover start (queue drain)"
PYTHONPATH=. .venv/bin/python -m strata.graphify.cli cover \
  --per-file 10 --files-per-chunk 6 --max-passes 12 >> "$LOG" 2>&1

say "bridge start (connect communities)"
PYTHONPATH=. .venv/bin/python -m strata.graphify.cli build --bridge >> "$LOG" 2>&1

say "connect queue complete"
