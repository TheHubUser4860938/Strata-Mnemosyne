#!/usr/bin/env bash
# molt_open - hand Moltbook to Clio for a while: a fast heartbeat cadence and a wide comment
# budget, both as systemd drop-ins so the base units stay exactly as installed.
#
#   tools/molt_open.sh          # every 5 minutes (the owner's usual "go explore")
#   tools/molt_open.sh 10       # every 10 minutes
#
# Cadence and budget move together on purpose. The platform allows 1 comment per 20 s (60 s
# while an agent is under 24 h old) and 50 a day, so a 5-minute heartbeat is budget-bound, not
# plumbing-bound: three comments a pass spends the day's allowance in about four hours. A pass
# costs 103-153 s of the box, so at 5 minutes the model is busy roughly a third of the time and
# the curation sweep still finds its 240 s of silence.
#
# Pairs with tools/molt_focus.sh, which drops back to the installed 2-hour cadence.
set -u
EVERY=${1:-5}
D=~/.config/systemd/user
mkdir -p "$D/strata-molt.service.d" "$D/strata-molt.timer.d"
cat > "$D/strata-molt.timer.d/open.conf" <<U
# set by tools/molt_open.sh - the owner's "go explore" window, every $EVERY minutes
[Timer]
OnCalendar=
OnCalendar=*-*-* *:*:00
U
[ "$EVERY" != "1" ] && sed -i "s|OnCalendar=\*-\*-\* \*:\*:00|OnCalendar=*-*-* *:00/${EVERY}:00|" \
    "$D/strata-molt.timer.d/open.conf"
cat > "$D/strata-molt.service.d/open.conf" <<U
# set by tools/molt_open.sh - wide budget for a free window
[Service]
Environment=MOLT_ARGS=--max-replies 3 --max-comments 3 --max-facts 3 --day-comments 50
U
systemctl --user daemon-reload && systemctl --user restart strata-molt.timer
systemctl --user list-timers strata-molt.timer --no-pager | sed -n '1,3p'
