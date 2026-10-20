# Pi TV Display

Raspberry Pi–driven TV display: Google Drive photo slideshow, weekly/monthly Google Calendar views, clock, weather, night screen-off, and auto-update from GitHub.

## Layout
```
app/server.py     Flask app + API (/api/photos, /api/events, /api/status, /photos/<f>, /healthz)
app/services.py   PhotoSync (Drive -> local cache), CalendarService (tz-normalised events), night schedule
app/clients.py    Google Drive/Calendar clients + MockDrive/MockCalendar (fixtures)
app/static/       Kiosk web UI + settings.html; (slideshow; every 8 photos shows week, then month view)
fixtures/         Sample photos + events (relative to today: timed, all-day, multi-day, overnight, UTC)
install.sh        one-command Pi installer (--dry-run)
pitv              CLI (set-hours, show-config, screen, control, status)
docs/             PI_SETUP.md (beginner guide), SERVICE_ACCOUNT_SETUP.txt
deploy/           reference systemd units (install.sh generates the real ones with correct paths)
scripts/          update.sh (git pull/redeploy/rollback), kiosk.sh, screen.sh, check_secrets.py, install_hooks.sh, oauth_login.py
tests/            pytest suite
```

## Quick start (no Google account – mock mode)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
scripts/install_hooks.sh
PITV_MOCK=1 .venv/bin/python -m app.server     # open http://127.0.0.1:8080
.venv/bin/python -m pytest -q
```
Mock is also the default in `config.example.yaml` (`mock: true`).

## Pi setup
**New Pi? Follow [docs/PI_SETUP.md](docs/PI_SETUP.md)** (blank Pi 3B+ → running display). Short version, on Raspberry Pi OS Lite (64-bit; Trixie, or Bookworm Legacy) with user `pi` and hostname `pitv`:
```bash
git clone https://github.com/nizn1770/multimediaDisplay.git ~/pi-tv-display && cd ~/pi-tv-display && ./install.sh   # --dry-run to preview
sudo reboot
```
`install.sh` (idempotent) installs packages, the venv, `config.local.yaml` (from the example), systemd `pitv.service` and `pitv-update.timer`, the sudoers rule, the git hooks, and the kiosk (console autologin → startx → openbox → memory-limited Chromium).

## Config (`config.local.yaml`, gitignored)
The repo is public: only `config.example.yaml` (placeholders) is committed. Values in `config.local.yaml` override the example defaults.

| key | meaning |
|---|---|
| `mock` | `true` uses fixtures; set `false` for real Google |
| `timezone` | IANA tz used for calendar days, clock, night schedule |
| `drive.folder_id` | ID from the folder URL `drive.google.com/drive/folders/<ID>` |
| `drive.sync_interval_sec` | how often new/removed photos are synced (default 300) |
| `calendar.calendars` | list of `{id, name, color}`; color-codes events. ID from Calendar settings → "Integrate calendar" |
| `credentials.type` | `service_account` (recommended) or `oauth` |
| `weather.*` | Open-Meteo, no key. Default Minneapolis, MN (44.9778, -93.2650), `forecast_days: 3` |
| `night.off_at/on_at` | default 23:00 / 06:30 in `timezone` (America/Chicago) |
| `device.user/hostname` | default `pi` / `pitv` (docs; systemd units assume `/home/pi`) |
| `slideshow.seconds_per_photo`, `server.*` | |

Env overrides: `PITV_CONFIG=/path/to/config.local.yaml`, `PITV_MOCK=1|0`.

## Google credentials
**Service account (recommended)** — full step-by-step in [`docs/SERVICE_ACCOUNT_SETUP.txt`](docs/SERVICE_ACCOUNT_SETUP.txt). Summary: create GCP project → enable Drive + Calendar APIs → create service account → download JSON key → `scp` to `/home/pi/pi-tv-display/secrets/service-account.json` and `chmod 600` → share the Drive folder and each calendar with the service-account email (Viewer / "See all event details") → copy Calendar ID from "Integrate calendar" → put IDs in `config.local.yaml`, `mock: false`, restart.

**OAuth (alternative, uses your own account)**
1. Same project; OAuth consent screen (External, add yourself as test user; publish to avoid 7-day token expiry); Credentials → OAuth client ID → *Desktop app*; save JSON as `secrets/oauth-client.json`.
2. On a machine with a browser: `python scripts/oauth_login.py` → creates `secrets/token.json`; copy it to the Pi. Set `credentials.type: oauth`. Tokens auto-refresh.

Scopes are read-only (`drive.readonly`, `calendar.readonly`).

## Remote updates
- **Auto-update:** `pitv-update.timer` runs `scripts/update.sh` every 5 min: `git fetch`; if `origin/main` moved, hard-reset to it, reinstall deps if `requirements.txt` changed, restart `pitv.service` and health-check `/healthz` on the configured port. **Any** failure after the reset (pip, restart, health) rolls back to the previous commit and records the SHA in `.pitv-bad-commit`, which is skipped until origin moves past it (delete the file to force a retry). Branch via `PITV_BRANCH`. Logs: `journalctl -u pitv-update`. Force a run: `sudo systemctl start pitv-update`. The browser reloads itself every 6 h; for front-end changes immediately, `sudo systemctl restart pitv` then refresh (or reboot).
- Repo: `github.com/nizn1770/multimediaDisplay` (branch `main`). If private, use a read-only deploy key (`ssh-keygen -t ed25519`, add pubkey as GitHub Deploy Key, clone via `git@github.com:...`).
- **SSH:** `ssh pi@pitv.local`, then `cd ~/pi-tv-display`; edit `config.local.yaml`, `sudo systemctl restart pitv`, `journalctl -u pitv -f`.

## Screen hours, settings page, CLI
- Hours are in `config.local.yaml` (`night.on_at` / `night.off_at`, default 06:30 / 23:00 America/Chicago). The server checks them every 30 s and runs `scripts/screen.sh on|off` (HDMI-CEC + xrandr) on each change; there's no cron.
- `http://pitv.local:8080/settings` (LAN/private IPs only, optional `settings.pin`) edits the hours and sends prev/next/pause/resume/photos/week/month. It validates input, writes `config.local.yaml` atomically and applies immediately.
- PIN: leading zeros are kept (`0123`, `0000`, `{pin: 0123}` all stay strings); quoting is still recommended. `./pitv control` sends `$PITV_PIN`.
- CLI: `./pitv set-hours 06:30 23:00`, `./pitv night on|off`, `./pitv show-config [--reveal]`, `./pitv screen on|off`, `./pitv control <action>`, `./pitv status`, `./pitv get server.port`. Edits made by hand or with the CLI are picked up within 30 s without a restart.
- API: `GET/POST /api/settings` (`{on_at, off_at, enabled, pin}`), `POST /api/control` (`{action, pin}`).

## Pi 3B+ performance
- Decode RAM budget: the image header is checked before decoding. Baseline JPEGs decode at reduced scale (any size up to 150 MP); progressive JPEG and HEIC up to 12.5 MP; other formats up to 16 MP. Anything larger uses the Drive-rendered thumbnail (`thumbnailLink=s1920`, chosen up front when Drive reports the dimensions); if there's no thumbnail it's skipped with a warning. `PIL.Image.MAX_IMAGE_PIXELS` = 160 MP. Measured peaks per image (fresh process, ~26 MB baseline): 48 MP baseline JPEG 53 MB, 12 MP progressive 73 MB, 12 MP HEIC 111 MB, 16 MP PNG ~109 MB, oversized ~27 MB. Check one with `scripts/measure_decode.py IMG`.
- Photos are EXIF-rotated, downscaled to fit `slideshow.max_width` x `max_height` (default 1920x1080, never upscaled) and re-encoded as JPEG q85 at sync time. Originals never reach the browser. The cache is capped at `drive.max_cache_mb` (default 500); the oldest photos by Drive modified time are dropped first.
- Chromium runs with one renderer process, no extensions, a 32 MB disk cache, a JS heap cap and a throwaway profile, and restarts if it crashes. The page reloads every 6 h. The CSS uses only opacity transitions (no blur, shadows or filters).
- Recommended: swap (rpi-swap on Trixie / 256 MB dphys on Bookworm), `gpu_mem` default (128 max), the official 5V 2.5A PSU (see docs/PI_SETUP.md).

## Keeping secrets out of the repo
- `scripts/install_hooks.sh` installs a pre-commit hook running `scripts/check_secrets.py --staged`.
- `python3 scripts/check_secrets.py --history` scans all tracked files and full git history (also run by pytest).
- It flags Drive-ID-like strings, private keys, client secrets, `@group.calendar.google.com` IDs, service-account emails, API keys, and specific known real IDs (stored only as SHA-256 hashes). Lines containing `YOUR_`/`example` are allowed placeholders.

## Behaviour notes
- Photo sync: downloads only new/changed files (manifest by `modifiedTime`), one at a time, writes atomically, prunes deleted ones. JPEG, PNG, GIF, WebP, BMP, TIFF and HEIC are supported; other types and corrupt files are recorded as skipped and retried only if changed. Capped photos come back when space frees up. Photo URLs carry `?v=` so changed photos aren't cached stale; if Drive is unreachable the existing cache keeps showing.
- API: `/api/photos` and `/api/events` return `offline` (the last fetch failed, so cached data is shown) separately from `warnings` (skipped files or events). The TV shows an offline banner only when `offline` is true; warnings appear as a small ⚠N next to "last synced".
- UI extras: 3-day forecast, today's agenda strip (next 3 events), "last synced" indicator, per-calendar colors.
- Calendar: fetches previous week through ~7 weeks; all-day end dates are exclusive; timed events are converted to `timezone` and span every day they touch; cancelled events ignored; malformed events are skipped and reported as `warnings`; duplicates across calendars are merged by iCalUID; times without an offset use the event's timeZone (else `timezone`); last good data kept when offline (UI shows "Calendar offline (cached)").

## Testing / injecting clients
`create_app(cfg, drive=..., calendar=..., start_background=False, weather_fn=...)` accepts any objects with:
- drive: `list_images() -> [{id,name,mimeType,modifiedTime}]`, `download(id, dest_path)`
- calendar: `list_events(calendar_id, time_min, time_max) -> [Google event dicts]`

See `tests/test_all.py` (`FakeDrive`, `FakeCal`) for examples including offline simulation.
