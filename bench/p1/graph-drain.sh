#!/usr/bin/env bash
# The graph drain (2026-11-16, workers knob 2026-11-18): repeated merge passes over the rows
# no node names yet, at 10 facts a file, then ONE bridge pass that wires the communities
# together. Runs unattended; progress.json is the truth the web page reads.
#
# --workers 2 is the measured middle: four concurrent chunks starved the 4090 and produced
# timeouts (2026-11-16); two streams on this MoE decode nearly free. Drop to 1 if a pass
# starts timing out.
#
# Log: ~/Strata-data/bench/p1/graph-drain-<date>.log ; queue: <store>/strata-graphify/pending.json
set -u
cd /home/eugene/Projects/Strata-Mnemosyne || exit 1
LOG=/home/eugene/Strata-data/bench/p1/graph-drain-$(date +%F).log
echo "=== drain started $(date -Is) ===" >> "$LOG"
.venv/bin/python -m strata.graphify.cli cover --per-file 10 --files-per-chunk 6 \
  --max-passes 20 --workers 2 >> "$LOG" 2>&1
echo "=== bridge $(date -Is) ===" >> "$LOG"
.venv/bin/python -m strata.graphify.cli build --bridge >> "$LOG" 2>&1
echo "=== drain finished $(date -Is) ===" >> "$LOG"
