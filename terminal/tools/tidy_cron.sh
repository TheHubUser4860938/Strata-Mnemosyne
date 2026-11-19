#!/usr/bin/env bash
# Weekly shelf maintenance: the taxonomy needs a keeper (the owner's law, 2026-11-11 - "the
# system must sort thousands of rows properly to be worth having").  A shelf label is a guess
# about meaning, so a week of harvesting leaves rows WILD (no call number: they ride every
# unfiltered request and join no filtered one) and cutters that were named for one fact.
#
# The pass, in the order that pays:
#   1. m4_shelves    - cluster the wild rows by cosine and PRINT the subjects big enough to be
#                      a cutter.  Proposals only, for the owner's eye in the log.
#   2. m4_reshelve   - the clerk files the wild rows against the store's own shelf list.
#   3. m4_shelftidy  - the two edges: invented tops onto a family, cutters under the 3-row bar
#                      rolled up into it.
# The MEM/CAT labels ride the 30-minute sweep already (sweep_cron.sh), so they are not repeated
# here.  Steps 2 and 3 ask the served model, so the window wants a quiet engine: this box runs
# it Saturday 01:00 with the machine left on.
#
# Measured arc on this box: 583 wild rows (26% of 2,226) on 2026-11-02, 63 (2.8%) on 107
# shelves after the first pass.  A wild shelf only waits; a false shelf HIDES a fact - so read
# the review log it writes (~/Strata-data/bench/m4-reshelve-<date>-<class>.jsonl).
#
# Install on THIS dev box (no cron daemon - systemd user timer, weekly):
#   units at ~/.config/systemd/user/strata-tidy.{service,timer} - INSTALLED + ENABLED
#   2026-11-11, Sat 01:00, Persistent=true so a Saturday with the box off runs at the next boot.
#   Check: systemctl --user list-timers strata-tidy.timer
#   Force: systemctl --user start strata-tidy.service
#   Remove: systemctl --user disable --now strata-tidy.timer && rm ~/.config/systemd/user/strata-tidy.*
# Where cron exists: 0 1 * * 6 ~/Projects/Strata-Mnemosyne/tools/tidy_cron.sh
#
# One caveat worth knowing: m4_shelves clusters on the vectors the store already carries, and
# embeds only the rows that have none - so on a store whose vectors are all one model, the
# centroids are that model's space.  A store that mixes stamps clusters across both.
set -u
cd "$(dirname "$0")/.."
URL=${STRATA_URL:-http://127.0.0.1:8005}
LOG=${TIDY_LOG:-tools/state/tidy.log}
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3      # the venv carries psycopg; the system interpreter does not

# Guard: no server, no clerk.  Skip the week quietly; the timer ticks on.
curl -sf --max-time 10 "$URL/memory" >/dev/null 2>&1 || {
    echo "$(date '+%F %T') tidy skipped: server down at $URL"; exit 0; }

echo "===== $(date '+%F %T') tidy start"
flock -n -E 9 tools/state/tidy.lock bash -c "
  $PY tools/m4_shelves.py --min 5 &&
  $PY tools/m4_reshelve.py --class WILD --apply &&
  $PY tools/m4_shelftidy.py --tops --roll --apply
" >> "$LOG" 2>&1
rc=$?
case "$rc" in
  9) echo "$(date '+%F %T') tidy skipped: lock held by a live tidy" ;;
  0) echo "$(date '+%F %T') tidy done" ;;
  *) echo "$(date '+%F %T') tidy failed rc=$rc - see $LOG" ;;
esac
