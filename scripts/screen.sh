#!/usr/bin/env bash
# Usage: screen.sh on|off   HDMI-CEC (TV standby) if available, plus X output/DPMS.
MODE=${1:?usage: screen.sh on|off}
case "$MODE" in on|off) ;; *) echo "usage: screen.sh on|off" >&2; exit 2;; esac
export DISPLAY=${DISPLAY:-:0}
OUT=${PITV_OUTPUT:-HDMI-1}
if command -v cec-client >/dev/null; then
  if [ "$MODE" = off ]; then echo 'standby 0' | cec-client -s -d 1; else echo 'on 0' | cec-client -s -d 1; fi
fi
if command -v xrandr >/dev/null && xrandr >/dev/null 2>&1; then
  if [ "$MODE" = off ]; then xrandr --output "$OUT" --off; else xrandr --output "$OUT" --auto; fi
elif command -v vcgencmd >/dev/null; then
  vcgencmd display_power "$([ "$MODE" = on ] && echo 1 || echo 0)"
fi
exit 0
