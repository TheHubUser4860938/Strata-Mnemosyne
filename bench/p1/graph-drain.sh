#!/usr/bin/env bash
# The graph drain (2026-11-16): the standing pass finishes, then cover() drains the store —
# repeated merge passes over only the rows no node names yet, at 10 facts a file. One job at a
# time on the 4090, because four concurrent chunks is what produced the timeouts in the first
# place. Logs: /tmp/opencode/gf-cover.log ; progress: <store>/strata-graphify/progress.json
set -u
cd /home/eugene/Projects/Strata-Mnemosyne || exit 1
P=/home/eugene/Strata-data/memory-eval/strata-graphify/progress.json
echo "queue started $(date -Is)" >> /tmp/opencode/gf-cover.log
while grep -q '"running": true' "$P" 2>/dev/null; do sleep 30; done
echo "standing pass done, cover starting $(date -Is)" >> /tmp/opencode/gf-cover.log
PYTHONPATH=. .venv/bin/python -m strata.graphify.cli cover --per-file 10 --files-per-chunk 6 \
  --max-passes 20 >> /tmp/opencode/gf-cover.log 2>&1
echo "cover finished $(date -Is)" >> /tmp/opencode/gf-cover.log
# Bridge the communities once the rows are in: one pass over the graph's own groups, which is
# what makes the recall arm's votes reach across shelves instead of around one drawer.
PYTHONPATH=. .venv/bin/python -m strata.graphify.cli build --bridge >> /tmp/opencode/gf-cover.log 2>&1
echo "bridge finished $(date -Is)" >> /tmp/opencode/gf-cover.log
