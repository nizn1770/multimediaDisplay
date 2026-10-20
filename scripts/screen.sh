#!/usr/bin/env bash
# Usage: screen.sh on|off
# 1) HDMI-CEC: puts the TV itself in standby / wakes it (needs cec-utils and CEC enabled on the TV).
# 2) Fallback: turn the Pi's HDMI output off/on: xrandr (X11 kiosk) or wlr-randr (Wayland).
# Note: `vcgencmd display_power` does nothing under the KMS driver (default on Bookworm/Trixie), so it is not used.
MODE=${1:-}
case "$MODE" in on|off) ;; *) echo "usage: screen.sh on|off" >&2; exit 2;; esac
export DISPLAY=${DISPLAY:-:0}
OUT=${PITV_OUTPUT:-HDMI-1}
did=0
if command -v cec-client >/dev/null; then
  if [ "$MODE" = off ]; then CMD='standby 0'; else CMD='on 0'; fi
  if echo "$CMD" | timeout 15 cec-client -s -d 1 >/dev/null 2>&1; then did=1; echo "cec: $CMD"; fi
  # Switch the TV input to the Pi when waking it.
  [ "$MODE" = on ] && echo 'as' | timeout 15 cec-client -s -d 1 >/dev/null 2>&1
fi
if command -v xrandr >/dev/null && xrandr >/dev/null 2>&1; then
  if [ "$MODE" = off ]; then xrandr --output "$OUT" --off; else xrandr --output "$OUT" --auto; fi && did=1 && echo "xrandr: $OUT $MODE"
elif command -v wlr-randr >/dev/null && [ -n "${WAYLAND_DISPLAY:-}" ]; then
  wlr-randr --output "${PITV_OUTPUT:-HDMI-A-1}" --"$MODE" && did=1 && echo "wlr-randr: $MODE"
fi
[ "$did" = 1 ] || echo "screen.sh: no CEC/xrandr/wlr-randr available; the page still blanks itself at night" >&2
exit 0
