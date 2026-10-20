# Pi TV Display: from a blank Raspberry Pi to a running display

Written for a **Raspberry Pi 3B+ (1 GB RAM)**. A Pi 4 or 5 also works with the same steps; those use **micro-HDMI** cables.

## 1. What you need
| Item | Notes |
|---|---|
| Raspberry Pi 3B+ | 1 GB RAM. Tuned for it (lightweight OS, downscaled photos, memory-limited browser). |
| Power supply | **Official Raspberry Pi 5V 2.5A micro-USB supply.** Phone chargers often under-volt: you get a lightning-bolt icon, random freezes and SD-card corruption. |
| microSD card | 16–32 GB, A1/A2 class (SanDisk/Samsung "Endurance" or "Pro" are good). |
| HDMI cable | **Full-size HDMI** on the 3B+ (micro-HDMI on Pi 4/5). |
| Network | Wi-Fi (2.4 GHz on the 3B+ works best) or Ethernet. |
| A computer | Mac or Windows, with an SD-card reader, to flash the card. |
| Optional | A case with a heatsink; a USB keyboard for troubleshooting. |

## 2. Flash Raspberry Pi OS **Lite** (64-bit, Bookworm)
Lite has no desktop, which saves about 300 MB of RAM. The installer adds only a minimal X server, the openbox window manager and Chromium.

1. Install **Raspberry Pi Imager** from https://www.raspberrypi.com/software/ and open it.
2. **Device:** Raspberry Pi 3. **OS:** *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)** (Bookworm). **Storage:** your microSD card.
3. Click **Next → Edit settings**:
   - *General*: hostname **`pitv`**; username **`pi`** with a password you'll remember; Wi-Fi SSID + password; Wi-Fi country **US**; locale time zone **America/Chicago**, keyboard **us**.
   - *Services*: **Enable SSH** → "Use password authentication" (or paste your public key).
4. **Save → Yes → Yes** to write. It takes about 5 minutes. Eject the card.

## 3. First boot and SSH
1. Put the card in the Pi, connect HDMI to the TV, then plug in power. The first boot takes 2–3 minutes and the Pi may reboot once. The TV shows a text login prompt, which is expected.
2. From your computer (on the same Wi-Fi):
   - **Mac:** open *Terminal* and run `ssh pi@pitv.local`
   - **Windows 10/11:** open *PowerShell* and run `ssh pi@pitv.local`
   - Type `yes` to trust the host, then your password.
   - If `pitv.local` isn't found, look up the Pi's IP in your router's device list and use `ssh pi@192.168.x.y`.
3. Update the system: `sudo apt update && sudo apt full-upgrade -y && sudo reboot`, then SSH back in.

## 4. Performance setup for the 3B+ (recommended, 2 minutes)
- **Swap (256 MB).** This gives Chromium headroom without wearing the SD card:
  ```bash
  sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=256/' /etc/dphys-swapfile
  sudo systemctl restart dphys-swapfile && free -m
  ```
  If `/etc/dphys-swapfile` doesn't exist (newer images use zram), skip this step.
- **GPU memory.** Chromium needs a little GPU memory for smooth fades. Keep it modest on 1 GB:
  ```bash
  echo 'gpu_mem=128' | sudo tee -a /boot/firmware/config.txt
  ```
  Use 128 (the default 76 can cause black or garbled frames; 256 starves the system).
- **720p TV or stutter?** In `config.local.yaml` set `slideshow.max_width: 1280` and `max_height: 720`. To force 1080p output, add `hdmi_group=1` and `hdmi_mode=16` to `/boot/firmware/config.txt`.
- Reboot after these changes: `sudo reboot`.

## 5. One-command install
```bash
git clone https://github.com/nizn1770/multimediaDisplay.git ~/pi-tv-display && cd ~/pi-tv-display && ./install.sh
```
It's safe to run again; it skips anything already done. Preview without changing anything: `./install.sh --dry-run`. On a 3B+ it takes about 10–15 minutes, mostly installing Chromium.

What it does:
- Installs packages: `git python3-venv curl chromium-browser xserver-xorg x11-xserver-utils xinit openbox unclutter cec-utils`.
- Creates `.venv` and installs the Python requirements.
- Creates `config.local.yaml` from the example if it's missing (`chmod 600`), and creates `secrets/` (`chmod 700`).
- Sets up the git remote and installs the secret-scanning pre-commit hook.
- Installs `pitv.service` (the display server), `pitv-update.service` + `pitv-update.timer` (auto-pull from GitHub every 5 minutes), and `/etc/sudoers.d/pitv`, which lets only `systemctl restart pitv.service` run without a password.
- Sets up the kiosk: console autologin (`raspi-config` B2) → `~/.bash_profile` runs `startx` on tty1 → `~/.xinitrc` disables screen blanking, hides the cursor and starts openbox → `~/.config/openbox/autostart` runs `scripts/kiosk.sh`, which starts memory-limited Chromium and restarts it if it crashes.

Finally: `sudo reboot`. The TV should show the slideshow with sample photos (mock mode).

## 6. Connect Google Drive + Calendar
Follow **[docs/SERVICE_ACCOUNT_SETUP.txt](SERVICE_ACCOUNT_SETUP.txt)**. Then edit `~/pi-tv-display/config.local.yaml` (`nano config.local.yaml`): set `mock: false`, the Drive folder ID and the calendar ID. Apply with `sudo systemctl restart pitv`.
Never commit this file. It's gitignored, and the pre-commit hook blocks IDs and keys.

## 7. Screen hours and remote control
- Defaults: on **06:30**, off **23:00** (America/Chicago), stored in `config.local.yaml` under `night:`.
- **From a phone or laptop on your Wi-Fi:** open `http://pitv.local:8080/settings`. You can edit the hours, turn night-off on or off, and use prev/next/pause/resume/photos/week/month. Changes apply immediately, with no restart. Only private (LAN) addresses can reach it. Optional PIN: set `settings.pin: "1234"` in `config.local.yaml`.
- **From SSH:**
  ```bash
  cd ~/pi-tv-display
  ./pitv set-hours 06:30 23:00   # ON then OFF, 24h HH:MM; applies within 30 s
  ./pitv night off               # disable night screen-off
  ./pitv show-config             # effective config (IDs masked; --reveal to show)
  ./pitv screen off|on           # switch the TV now
  ./pitv control next|pause|week # drive the display
  ./pitv status
  ```
- The app itself switches the screen. Every 30 s it reads the hours and runs `scripts/screen.sh on|off`, which uses HDMI-CEC to put the TV in standby when supported (`cec-utils`) and turns off the HDMI output with `xrandr`. Between those times the page also shows black. There's no cron.

## 8. Verify
```bash
systemctl status pitv pitv-update.timer --no-pager
curl -s http://127.0.0.1:8080/healthz          # -> ok
curl -s http://127.0.0.1:8080/api/photos | head -c 300
journalctl -u pitv -n 50 --no-pager            # server log (sync/calendar errors show here)
journalctl -u pitv-update -n 20 --no-pager     # auto-update log
free -m; vcgencmd measure_temp; vcgencmd get_throttled   # throttled=0x0 is good
```

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| TV shows a text login prompt, no browser | Autologin missing: `sudo raspi-config` → System Options → Boot/Auto Login → *Console Autologin*. Check `cat /tmp/pitv-x.log`. Re-run `./install.sh`. |
| "Server unreachable" on screen | `systemctl status pitv`, `journalctl -u pitv -n 50`. Usually a YAML typo in `config.local.yaml`; `./pitv show-config` shows parse errors. |
| Sample photos instead of yours | `mock: true` is still set, or the folder isn't shared with the service-account email. Check `journalctl -u pitv | grep -i drive`. |
| Calendar empty / "Calendar offline" | Calendar not shared with the service account, or wrong calendar ID. |
| Lightning-bolt icon / random freezes | Under-voltage: use the official 2.5A supply. `vcgencmd get_throttled` should be `0x0`. |
| Slow or stuttery fades | Set `gpu_mem=128`, add 256 MB swap, use 1280x720 photos (section 4). |
| Browser crashes / blank after days | Chromium auto-restarts and the page reloads every 6 h. Check `free -m` and `dmesg | grep -i oom`. |
| TV doesn't turn off at night | TV lacks or disables HDMI-CEC (enable "Anynet+/Bravia Sync/SimpLink"). The output still goes black. Test with `./pitv screen off`. |
| `pitv.local` not found | Use the IP from your router. On Windows, install Bonjour or use the IP. |
| Auto-update not applying | `journalctl -u pitv-update`. Local edits to tracked files are overwritten on update; keep changes in `config.local.yaml`. |
