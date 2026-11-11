#!/usr/bin/env bash
# molt_focus - call Clio back to work: drop the "go explore" cadence and budget, return to the
# installed heartbeat (every 2 hours at :15, 1-2 comments a pass, 12 a day).  The drop-ins are
# deleted, not edited, so `molt_open.sh` always starts from the installed shape.
#
#   tools/molt_focus.sh
set -u
D=~/.config/systemd/user
rm -f "$D/strata-molt.timer.d/open.conf" "$D/strata-molt.service.d/open.conf"
rmdir "$D/strata-molt.timer.d" "$D/strata-molt.service.d" 2>/dev/null || true
systemctl --user daemon-reload && systemctl --user restart strata-molt.timer
systemctl --user list-timers strata-molt.timer --no-pager | sed -n '1,3p'
