#!/usr/bin/env bash
# Usage: screen.sh on|off  (wlr-randr on Bookworm/Wayland, fallback to HDMI-CEC via cec-client)
MODE=$1; OUT=${PITV_OUTPUT:-HDMI-A-1}
if command -v wlr-randr >/dev/null; then wlr-randr --output "$OUT" --"$MODE"; fi
if command -v cec-client >/dev/null; then
  if [ "$MODE" = off ]; then echo 'standby 0' | cec-client -s -d 1; else echo 'on 0' | cec-client -s -d 1; fi
fi
