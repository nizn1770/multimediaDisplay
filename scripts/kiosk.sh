#!/usr/bin/env bash
# Launch Chromium fullscreen once the server is healthy. Flags tuned for a 1 GB Pi 3B+.
until curl -fs http://127.0.0.1:8080/healthz >/dev/null; do sleep 2; done
B=$(command -v chromium-browser || command -v chromium)
PROFILE=/tmp/pitv-chromium   # fresh profile each boot (tmpfs-friendly, no growth)
rm -rf "$PROFILE"
while true; do   # relaunch if the browser ever crashes / gets OOM-killed
  "$B" --kiosk --noerrdialogs --disable-infobars --no-first-run --incognito \
    --user-data-dir="$PROFILE" --disk-cache-dir=/tmp/pitv-cache --disk-cache-size=33554432 \
    --media-cache-size=1 --disable-extensions --disable-component-update \
    --disable-features=Translate,MediaRouter,OptimizationHints,AutofillServerCommunication \
    --process-per-site --renderer-process-limit=1 --disable-background-networking \
    --disable-sync --disable-default-apps --disable-session-crashed-bubble \
    --check-for-update-interval=31536000 --password-store=basic \
    --js-flags=--max-old-space-size=128 --enable-low-end-device-mode \
    http://127.0.0.1:8080/
  sleep 5
done
