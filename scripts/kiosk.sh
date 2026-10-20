#!/usr/bin/env bash
# Launch Chromium fullscreen on the display once the server is healthy.
until curl -fs http://127.0.0.1:8080/healthz >/dev/null; do sleep 2; done
exec chromium-browser --kiosk --noerrdialogs --disable-infobars --incognito \
  --disable-session-crashed-bubble --check-for-update-interval=31536000 http://127.0.0.1:8080/
