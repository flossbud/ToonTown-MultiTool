#!/usr/bin/env bash
# Start, watch or stop the float-strip playground on a Linux desktop session.
#
#   scripts/strip_play.sh start [neon|flat]   open it (as a user service)
#   scripts/strip_play.sh log                 follow what the clicks do
#   scripts/strip_play.sh stop                end it; nothing is left running
#
# PYTHON=/path/to/venv/bin/python picks the interpreter (PySide6 + python-xlib).
# Run it from a terminal on that desktop, or over ssh: the service gets the
# session's display from the environment below.
set -euo pipefail
UNIT=ttmt-strips-play
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
RUNTIME="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

case "${1:-}" in
  start)
    systemctl --user stop "$UNIT" 2>/dev/null || true
    systemctl --user reset-failed "$UNIT" 2>/dev/null || true
    XAUTH="${XAUTHORITY:-$(ls "$RUNTIME"/xauth_* 2>/dev/null | head -1)}"
    systemd-run --user --unit="$UNIT" --collect \
      -E DISPLAY="${DISPLAY:-:0}" -E XAUTHORITY="$XAUTH" \
      -E XDG_RUNTIME_DIR="$RUNTIME" \
      -E DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME/bus" \
      -E QT_QPA_PLATFORM=xcb -E PYTHONUNBUFFERED=1 \
      --working-directory="$(dirname "$HERE")" \
      "$PYTHON" "$HERE/strip_demo.py" --play --style "${2:-neon}"
    echo "started; '$0 log' shows the actions, '$0 stop' ends it"
    ;;
  log)
    exec journalctl --user -u "$UNIT" -f -o cat
    ;;
  stop)
    systemctl --user stop "$UNIT" 2>/dev/null || true
    sleep 0.5
    # Bracketed so the pattern never matches the shell that carries it.
    LEFT='strip_demo[.]py --play|strip_standin[.]py game'
    if pgrep -f "$LEFT" >/dev/null; then
      echo "still running:"; pgrep -af "$LEFT"; exit 1
    fi
    echo "stopped; nothing left running"
    ;;
  *)
    sed -n '2,10p' "$0"; exit 2
    ;;
esac
