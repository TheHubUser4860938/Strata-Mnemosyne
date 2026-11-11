#!/usr/bin/env bash
# Moltbook heartbeat: one unattended pass of Clio's social work - answer the replies on my
# posts, add one comment to the feed, file what is worth keeping.  The judgment is the served
# model's (tools/molt_loop.py); this file owns the door: guard, lock, budget, log.
#
# Cadence: every 2 hours, 12 passes a day, 1-3 comments each - inside the platform's 50/day
# (20/day while the account is under 24 h old) with room left for the daytime hours when the
# owner is in a conversation.  Each pass is 2-3 engine calls plus the 60 s comment cooldown, so
# about 2.5 minutes of the box; the curation sweep wants 240 s of silence for itself and gets
# the other 87 minutes.
#
# Install on THIS dev box (systemd user timer, no cron daemon):
#   units at ~/.config/systemd/user/strata-molt.{service,timer} - INSTALLED + ENABLED
#   2026-11-11.  Check: systemctl --user list-timers strata-molt.timer
#   Force: systemctl --user start strata-molt.service
#   Remove: systemctl --user disable --now strata-molt.timer && rm ~/.config/systemd/user/strata-molt.*
# Where cron exists: 15 */2 * * * ~/Projects/Strata-Mnemosyne/tools/molt_cron.sh
set -u
cd "$(dirname "$0")/.."
URL=${STRATA_URL:-http://127.0.0.1:8005}
LOG=${MOLT_LOG:-tools/state/molt.log}
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

# No server, no model, no pass.  Skip quietly; the timer ticks on.
curl -sf --max-time 10 "$URL/memory" >/dev/null 2>&1 || {
    echo "$(date '+%F %T') molt skipped: server down at $URL" >> "$LOG"; exit 0; }

flock -n -E 9 tools/state/molt.lock "$PY" tools/molt_loop.py --url "$URL" --tag cron >> "$LOG" 2>&1
rc=$?
[ "$rc" = 9 ] && echo "$(date '+%F %T') molt skipped: lock held by a live pass" >> "$LOG"
exit 0
