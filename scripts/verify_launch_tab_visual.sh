#!/usr/bin/env bash
# Visual verification gate for the Launch tab redesign.
# Boots TTMT in demo mode (which auto-selects the Launch tab), captures
# populated + empty states, saves to /tmp.
# Usage: scripts/verify_launch_tab_visual.sh
set -euo pipefail

OUT_DIR="/tmp/ttmt-launch-tab-verify"
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/*.png

command -v xdotool >/dev/null || { echo "xdotool required"; exit 1; }
command -v import   >/dev/null || { echo "ImageMagick 'import' required"; exit 1; }

# Find a TTMT window owned by one of the given PIDs (parent or any of its
# children). main.py re-execs into the venv, so the GUI window is owned by a
# child of the launched shell process.
find_window_for_pids() {
  local pids="$1"
  local pid
  for pid in $pids; do
    local ids
    ids=$(xdotool search --pid "$pid" 2>/dev/null || true)
    local id
    for id in $ids; do
      local name
      name=$(xdotool getwindowname "$id" 2>/dev/null || true)
      case "$name" in
        *ToonTown*MultiTool*|*TTMT*)
          echo "$id"
          return 0
          ;;
      esac
    done
  done
  return 1
}

capture() {
  local mode="$1"
  local out="$2"
  TTMT_DEMO_LAUNCH_TAB="$mode" TTMT_NO_VENV_REEXEC=1 venv/bin/python main.py &
  local TTMT_PID=$!
  # Give the GUI time to draw. Re-exec into venv + Qt init takes a few seconds.
  sleep 8
  # main.py may have re-execed; gather the parent + descendants.
  local PIDS
  PIDS=$(pstree -p "$TTMT_PID" 2>/dev/null | grep -oE '\([0-9]+\)' | tr -d '()' | tr '\n' ' ' || echo "$TTMT_PID")
  local WIN_ID
  WIN_ID=$(find_window_for_pids "$PIDS" || true)
  if [ -z "$WIN_ID" ]; then
    echo "No TTMT window found for mode=$mode (pids=$PIDS)" >&2
    kill "$TTMT_PID" 2>/dev/null || true
    return 1
  fi
  xdotool windowactivate "$WIN_ID" 2>/dev/null || true
  sleep 1
  import -window "$WIN_ID" "$out"
  # Kill the whole process tree (parent shell + venv re-exec child).
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  wait "$TTMT_PID" 2>/dev/null || true
  sleep 1
}

capture "populated" "$OUT_DIR/populated.png"
capture "empty"     "$OUT_DIR/empty.png"

ls -la "$OUT_DIR"/*.png
echo ""
echo "Captures saved. Review against .superpowers/brainstorm/392264-1779376335/content/complete-mockup.html"
