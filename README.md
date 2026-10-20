# Pi TV Display

Raspberry Pi–driven TV display: Google Drive photo slideshow, weekly/monthly Google Calendar views, clock, weather, night screen-off, and auto-update from GitHub.

## Layout
```
app/server.py     Flask app + API (/api/photos, /api/events, /api/status, /photos/<f>, /healthz)
app/services.py   PhotoSync (Drive -> local cache), CalendarService (tz-normalised events), night schedule
app/clients.py    Google Drive/Calendar clients + MockDrive/MockCalendar (fixtures)
app/static/       Kiosk web UI (slideshow; every 8 photos shows week, then month view)
fixtures/         Sample photos + events (relative to today: timed, all-day, multi-day, overnight, UTC)
deploy/           systemd units: pitv.service, pitv-update.{service,timer}, pitv-screen@.service
scripts/          update.sh (git pull/redeploy/rollback), kiosk.sh, screen.sh, oauth_login.py
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
1. Flash **Raspberry Pi OS (64-bit, Bookworm) with Desktop** using Raspberry Pi Imager; in its settings enable SSH, set user `pi`, Wi-Fi, and hostname (e.g. `pitv`).
2. `sudo apt update && sudo apt install -y git python3-venv chromium-browser curl wlr-randr cec-utils`
3. `git clone https://github.com/nizn1770/multimediaDisplay.git ~/pi-tv-display && cd ~/pi-tv-display`
4. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
5. `cp config.example.yaml config.local.yaml` and edit it (see Config). `config.local.yaml` and `secrets/` are gitignored — real IDs/keys live only there.
6. Install services:
```bash
sudo cp deploy/pitv.service deploy/pitv-update.service deploy/pitv-update.timer /etc/systemd/system/
sudo cp deploy/pitv-screen.service /etc/systemd/system/pitv-screen@.service
sudo systemctl daemon-reload
sudo systemctl enable --now pitv.service pitv-update.timer
```
   If your user isn't `pi`, edit `User=` and paths in the units.
   `update.sh` restarts the service with sudo; allow it without a password:
   `echo 'pi ALL=NOPASSWD: /bin/systemctl restart pitv.service' | sudo tee /etc/sudoers.d/pitv`
7. **Kiosk autostart** (Bookworm/Wayfire): add to `~/.config/wayfire.ini`
```ini
[autostart]
pitv = /home/pi/pi-tv-display/scripts/kiosk.sh
```
   (On labwc, newer Bookworm: add the path to `~/.config/labwc/autostart`. On X11/LXDE: `@/home/pi/pi-tv-display/scripts/kiosk.sh` in `~/.config/lxsession/LXDE-pi/autostart`.) Enable desktop autologin with `sudo raspi-config` → System → Boot/Auto login. Disable screen blanking in raspi-config → Display.

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
- **Auto-update:** `pitv-update.timer` runs `scripts/update.sh` every 5 min: `git fetch`; if `origin/main` moved, hard-reset to it, reinstall deps if `requirements.txt` changed, restart `pitv.service`, health-check `/healthz`, and roll back to the previous commit on failure. Branch via `PITV_BRANCH`. Logs: `journalctl -u pitv-update`. Force a run: `sudo systemctl start pitv-update`. The browser reloads itself every 6 h; for front-end changes immediately, `sudo systemctl restart pitv` then refresh (or reboot).
- Repo: `github.com/nizn1770/multimediaDisplay` (branch `main`). If private, use a read-only deploy key (`ssh-keygen -t ed25519`, add pubkey as GitHub Deploy Key, clone via `git@github.com:...`).
- **SSH:** `ssh pi@pitv.local`, then `cd ~/pi-tv-display`; edit `config.yaml`, `sudo systemctl restart pitv`, `journalctl -u pitv -f`.

## Night screen-off
The UI blacks out during `night.off_at`–`on_at`. To actually power the TV/HDMI down, add timers or cron:
```
crontab -e
0 23 * * *  /home/pi/pi-tv-display/scripts/screen.sh off
30 6 * * *  /home/pi/pi-tv-display/scripts/screen.sh on
```
(`wlr-randr` for HDMI output, `cec-client` for TVs supporting HDMI-CEC.)

## Keeping secrets out of the repo
- `scripts/install_hooks.sh` installs a pre-commit hook running `scripts/check_secrets.py --staged`.
- `python3 scripts/check_secrets.py --history` scans all tracked files and full git history (also run by pytest).
- It flags Drive-ID-like strings, private keys, client secrets, `@group.calendar.google.com` IDs, service-account emails, API keys, and specific known real IDs (stored only as SHA-256 hashes). Lines containing `YOUR_`/`example` are allowed placeholders.

## Behaviour notes
- Photo sync: downloads only new/changed files (manifest by `modifiedTime`), writes atomically, prunes deleted ones; if Drive is unreachable the existing cache keeps showing.
- UI extras: 3-day forecast, today's agenda strip (next 3 events), "last synced" indicator, per-calendar colors.
- Calendar: fetches previous week through ~7 weeks; all-day end dates are exclusive; timed events are converted to `timezone` and span every day they touch; cancelled events ignored; last good data kept when offline (UI shows "Calendar offline (cached)").

## Testing / injecting clients
`create_app(cfg, drive=..., calendar=..., start_background=False, weather_fn=...)` accepts any objects with:
- drive: `list_images() -> [{id,name,mimeType,modifiedTime}]`, `download(id, dest_path)`
- calendar: `list_events(calendar_id, time_min, time_max) -> [Google event dicts]`

See `tests/test_all.py` (`FakeDrive`, `FakeCal`) for examples including offline simulation.
