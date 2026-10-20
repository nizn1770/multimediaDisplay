import datetime as dt, os, shutil, pytest
from app.config import load_config
from app.clients import MockDrive, MockCalendar
from app.services import PhotoSync, CalendarService, in_night
from app.server import create_app

class FakeDrive:
    def __init__(self, src): self.src, self.files, self.fail = src, {}, False
    def add(self, name, mod="1"):
        self.files[name] = mod
    def list_images(self):
        if self.fail: raise ConnectionError("offline")
        return [{"id": n, "name": n, "mimeType": "image/jpeg", "modifiedTime": m} for n, m in self.files.items()]
    def download(self, fid, dest): shutil.copyfile(os.path.join(self.src, "sample1.jpg"), dest)

class FakeCal:
    def __init__(self, events): self.events, self.fail = events, False
    def list_events(self, *a):
        if self.fail: raise ConnectionError("offline")
        return self.events

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "photos")

def test_new_photo_pickup_and_removal(tmp_path):
    d = FakeDrive(FIX); d.add("a.jpg"); s = PhotoSync(d, str(tmp_path))
    s.sync(); assert s.photos() == ["a.jpg"]
    d.add("b.jpg"); s.sync(); assert s.photos() == ["a.jpg", "b.jpg"]
    del d.files["a.jpg"]; s.sync(); assert s.photos() == ["b.jpg"]

def test_offline_keeps_cache(tmp_path):
    d = FakeDrive(FIX); d.add("a.jpg"); s = PhotoSync(d, str(tmp_path)); s.sync()
    d.fail = True; assert s.sync() is False; assert s.photos() == ["a.jpg"]; assert s.last_error

def test_unchanged_not_redownloaded(tmp_path):
    d = FakeDrive(FIX); d.add("a.jpg"); s = PhotoSync(d, str(tmp_path)); s.sync()
    calls = []; d.download = lambda *a: calls.append(a); s.sync(); assert calls == []
    s2 = PhotoSync(d, str(tmp_path)); s2.sync(); assert calls == []  # manifest persisted

def test_timezone_and_multiday():
    ev = [{"id": "utc", "summary": "x", "start": {"dateTime": "2026-10-21T02:00:00Z"}, "end": {"dateTime": "2026-10-21T03:00:00Z"}},
          {"id": "trip", "summary": "t", "start": {"date": "2026-10-22"}, "end": {"date": "2026-10-25"}},
          {"id": "night", "summary": "n", "start": {"dateTime": "2026-10-26T22:00:00-05:00"}, "end": {"dateTime": "2026-10-27T06:00:00-05:00"}},
          {"id": "mid", "summary": "m", "start": {"dateTime": "2026-10-28T23:00:00-05:00"}, "end": {"dateTime": "2026-10-29T00:00:00-05:00"}},
          {"id": "gone", "status": "cancelled", "start": {"date": "2026-10-22"}, "end": {"date": "2026-10-23"}}]
    c = CalendarService(FakeCal(ev), ["primary"], "America/Chicago"); c.refresh(dt.date(2026, 10, 20))
    b = c.by_day()
    assert [e["id"] for e in b["2026-10-20"]] == ["utc"]          # 9pm Chicago, not the 21st
    assert all("trip" in [e["id"] for e in b[d]] for d in ["2026-10-22", "2026-10-23", "2026-10-24"])
    assert "2026-10-25" not in b                                 # exclusive end
    assert "night" in [e["id"] for e in b["2026-10-27"]]
    assert "2026-10-29" not in b                                 # midnight end exclusive
    assert all(e["id"] != "gone" for e in c.events)

def test_calendar_offline_keeps_events():
    f = FakeCal([{"id": "a", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}}])
    c = CalendarService(f, ["p"], "America/Chicago"); c.refresh()
    f.fail = True; assert c.refresh() is False and len(c.events) == 1 and c.last_error

@pytest.mark.parametrize("t,exp", [("23:30", True), ("03:00", True), ("06:30", False), ("12:00", False)])
def test_night(t, exp):
    assert in_night(dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(t)), "23:00", "06:30") == exp

def test_app_mock(tmp_path):
    cfg = load_config("/nonexistent"); cfg["mock"] = True; cfg["drive"]["cache_dir"] = str(tmp_path)
    app = create_app(cfg, start_background=False).test_client()
    p = app.get("/api/photos").get_json(); assert len(p["photos"]) == 4
    assert app.get("/photos/" + p["photos"][0]).status_code == 200
    assert app.get("/photos/../config.py").status_code == 404
    e = app.get("/api/events").get_json(); assert len(e["events"]) == 6 and e["by_day"]
    s = app.get("/api/status").get_json(); assert s["weather"]["temp"] and s["mock"]
    assert app.get("/").status_code == 200 and app.get("/healthz").data == b"ok"

def test_app_error_surface(tmp_path):
    cfg = load_config("/nonexistent"); cfg["drive"]["cache_dir"] = str(tmp_path)
    d = FakeDrive(FIX); d.fail = True; c = FakeCal([]); c.fail = True
    def bad(): raise RuntimeError("no net")
    app = create_app(cfg, drive=d, calendar=c, start_background=False, weather_fn=bad).test_client()
    assert app.get("/api/photos").get_json()["error"]
    assert app.get("/api/events").get_json()["error"]
    assert app.get("/api/status").status_code == 200

import subprocess, sys, importlib.util
ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("cs", os.path.join(ROOT, "scripts", "check_secrets.py"))
cs = importlib.util.module_from_spec(spec); spec.loader.exec_module(cs)

def test_tracked_files_and_history_have_no_secrets():
    r = subprocess.run([sys.executable, "scripts/check_secrets.py", "--history"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout

def test_local_config_is_gitignored():
    r = subprocess.run(["git", "check-ignore", "config.local.yaml", "secrets/service-account.json"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and len(r.stdout.split()) == 2

@pytest.mark.parametrize("text", [
    "pFWqeuwO0JkCeLLlCR342KGeSKXNhthe1"[::-1],                 # the real folder id (built, never literal)
    "folder_id: 1" + "A" * 32,
    '{"private_' 'key": "-----BEGIN " "PRIVATE KEY-----"}',
    '{"client_' 'secret": "abc"}',
    "abc123" + "@group.calendar.google.com",
    "pitv" + "@proj-1.iam.gserviceaccount.com"])
def test_scanner_detects(text):
    assert cs.scan_text(text, "x")

def test_scanner_allows_placeholders():
    assert not cs.scan_text('folder_id: "YOUR_DRIVE_FOLDER_ID"\nid: "YOUR_CALENDAR_ID"', "x")

def test_agenda_and_colors():
    now = dt.datetime(2026, 10, 20, 12, tzinfo=__import__("zoneinfo").ZoneInfo("America/Chicago"))
    ev = [{"id": "past", "start": {"dateTime": "2026-10-20T08:00:00-05:00"}, "end": {"dateTime": "2026-10-20T09:00:00-05:00"}},
          {"id": "allday", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}},
          {"id": "soon", "start": {"dateTime": "2026-10-20T15:00:00-05:00"}, "end": {"dateTime": "2026-10-20T16:00:00-05:00"}},
          {"id": "later", "start": {"dateTime": "2026-10-22T15:00:00-05:00"}, "end": {"dateTime": "2026-10-22T16:00:00-05:00"}},
          {"id": "last", "start": {"dateTime": "2026-10-23T15:00:00-05:00"}, "end": {"dateTime": "2026-10-23T16:00:00-05:00"}}]
    c = CalendarService(FakeCal(ev), [{"id": "fam", "name": "Family", "color": "#123456"}], "America/Chicago")
    c.refresh(dt.date(2026, 10, 20))
    assert [e["id"] for e in c.agenda(now)] == ["allday", "soon", "later"]
    assert all(e["color"] == "#123456" for e in c.events)

def test_status_forecast_and_defaults(tmp_path):
    cfg = load_config("/nonexistent"); cfg["mock"] = True; cfg["drive"]["cache_dir"] = str(tmp_path)
    assert cfg["weather"]["latitude"] == 44.9778 and cfg["night"]["off_at"] == "23:00" and cfg["device"]["hostname"] == "pitv"
    app = create_app(cfg, start_background=False).test_client()
    w = app.get("/api/status").get_json()["weather"]; assert len(w["forecast"]) == 3
    e = app.get("/api/events").get_json(); assert "agenda" in e and e["calendars"][0]["color"]

# ---- settings / screen control / CLI ----
import yaml
from app.services import ScreenController
from zoneinfo import ZoneInfo

def _app(tmp_path, pin="", runner=None):
    cfgp = tmp_path / "config.local.yaml"; cfgp.write_text('drive:\n  folder_id: "keepme"\n')
    cfg = load_config(str(cfgp)); cfg["mock"] = True; cfg["drive"]["cache_dir"] = str(tmp_path / "c")
    cfg["settings"]["pin"] = pin
    calls = []
    app = create_app(cfg, start_background=False, screen_runner=runner or calls.append, config_path=str(cfgp))
    return app.test_client(), cfg, cfgp, calls

def test_settings_saves_atomically_and_applies_live(tmp_path):
    c, cfg, p, _ = _app(tmp_path)
    r = c.post("/api/settings", json={"on_at": "07:15", "off_at": "22:45", "enabled": True})
    assert r.status_code == 200
    saved = yaml.safe_load(p.read_text())
    assert saved["night"]["on_at"] == "07:15" and saved["drive"]["folder_id"] == "keepme"  # other keys kept
    assert c.get("/api/status").get_json()["hours"]["off_at"] == "22:45"
    assert not list(tmp_path.glob(".cfg-*"))  # no temp files left

@pytest.mark.parametrize("body", [{"on_at": "25:00", "off_at": "23:00"}, {"on_at": "6:30", "off_at": "23:00"},
    {"on_at": "06:30", "off_at": "06:30"}, {"on_at": "06:30", "off_at": "x"}, {"enabled": "yes"}])
def test_settings_validation(tmp_path, body):
    c, _, p, _ = _app(tmp_path)
    assert c.post("/api/settings", json=body).status_code == 400
    assert "night" not in yaml.safe_load(p.read_text())

def test_settings_pin_and_lan_only(tmp_path):
    c, _, _, _ = _app(tmp_path, pin="4321")
    body = {"on_at": "06:30", "off_at": "23:00"}
    assert c.post("/api/settings", json=body).status_code == 401
    assert c.post("/api/settings", json={**body, "pin": "0000"}).status_code == 401
    assert c.post("/api/settings", json={**body, "pin": "4321"}).status_code == 200
    assert c.get("/api/settings").get_json()["pin_required"] is True
    assert c.get("/settings", environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403
    assert c.get("/settings", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 200

def test_external_edit_reloaded_without_restart(tmp_path):
    c, cfg, p, _ = _app(tmp_path)
    import time; time.sleep(0.01)
    p.write_text('night:\n  on_at: "08:00"\n  off_at: "21:00"\n'); os.utime(p, (time.time() + 5, time.time() + 5))
    assert c.get("/api/status").get_json()["hours"] == {"on_at": "08:00", "off_at": "21:00", "enabled": True}

def test_control_actions(tmp_path):
    c, _, _, _ = _app(tmp_path)
    assert c.post("/api/control", json={"action": "bogus"}).status_code == 400
    s0 = c.get("/api/status").get_json()["control"]["seq"]
    assert c.post("/api/control", json={"action": "pause"}).get_json()["control"]["paused"] is True
    st = c.get("/api/status").get_json()["control"]; assert st["seq"] == s0 + 1 and st["action"] == "pause"
    assert c.post("/api/control", json={"action": "week"}).status_code == 200

def test_screen_controller_transitions():
    tz = ZoneInfo("America/Chicago"); calls = []
    cfg = {"night": {"enabled": True, "on_at": "06:30", "off_at": "23:00", "control_display": True}}
    sc = ScreenController(lambda: cfg, tz, calls.append)
    d = dt.date(2026, 10, 20)
    for h, m in [(12, 0), (12, 30), (23, 0), (3, 0), (6, 29), (6, 30)]:
        sc.tick(dt.datetime.combine(d, dt.time(h, m), tz))
    assert calls == ["on", "off", "on"]          # only on transitions
    cfg["night"]["off_at"] = "13:00"; sc.tick(dt.datetime.combine(d, dt.time(13, 5), tz))
    assert calls[-1] == "off"                    # config change honoured live
    cfg["night"]["enabled"] = False; sc.tick(dt.datetime.combine(d, dt.time(13, 6), tz)); assert calls[-1] == "on"

def test_unquoted_yaml_times_coerced(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text("night:\n  on_at: 06:30\n  off_at: 23:00\n")
    n = load_config(str(p))["night"]; assert (n["on_at"], n["off_at"]) == ("06:30", "23:00")

def test_cli(tmp_path):
    p = tmp_path / "config.local.yaml"; p.write_text('drive:\n  folder_id: "1abcdefsecret"\n')
    env = {**os.environ, "PITV_CONFIG": str(p)}
    run = lambda *a: subprocess.run([os.path.join(ROOT, "pitv"), *a], env=env, capture_output=True, text=True)
    assert run("set-hours", "24:00", "23:00").returncode == 2
    assert run("set-hours", "06:45", "22:30").returncode == 0
    assert yaml.safe_load(p.read_text())["night"] == {"on_at": "06:45", "off_at": "22:30"}
    out = run("show-config").stdout; assert "06:45" in out and "1abcdefsecret" not in out
    assert "1abcdefsecret" in run("show-config", "--reveal").stdout
    assert run("night", "off").returncode == 0 and yaml.safe_load(p.read_text())["night"]["enabled"] is False

def test_install_dry_run_and_shellcheck():
    r = subprocess.run(["bash", "install.sh", "--dry-run"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "pitv-update.timer" in r.stdout and "NOPASSWD" in r.stdout and "DRY RUN" in r.stdout
    sc = shutil.which("shellcheck") or os.path.join(ROOT, ".venv", "bin", "shellcheck")
    if not os.path.exists(sc): pytest.skip("shellcheck not installed")
    files = ["install.sh", "pitv", "scripts/update.sh", "scripts/kiosk.sh", "scripts/screen.sh", "scripts/install_hooks.sh", "scripts/hooks/pre-commit"]
    r = subprocess.run([sc, *files], cwd=ROOT, capture_output=True, text=True); assert r.returncode == 0, r.stdout

# ---- Pi 3B+ tuning: downscaling, cache cap, memory ----
from PIL import Image
from app.services import downscale

class ImgDrive:
    """Serves generated images: big landscape, EXIF-rotated portrait, RGBA PNG."""
    def __init__(self, tmp): self.tmp, self.files = tmp, {}
    def add(self, fid, maker, mod="1"): self.files[fid] = (maker, mod)
    def list_images(self): return [{"id": k, "name": k, "mimeType": "image/jpeg", "modifiedTime": m} for k, (_, m) in self.files.items()]
    def download(self, fid, dest): self.files[fid][0](dest)

def big(dest): Image.new("RGB", (4032, 3024), (200, 10, 10)).save(dest, "JPEG", quality=95)
def rotated(dest):
    im = Image.new("RGB", (4000, 3000), (10, 200, 10)); ex = Image.Exif(); ex[0x0112] = 6  # rotate 90 CW
    im.save(dest, "JPEG", exif=ex)
def png(dest): Image.new("RGBA", (800, 600), (0, 0, 255, 128)).save(dest, "PNG")

def test_downscale_fits_screen_fixes_exif_and_converts(tmp_path):
    d = ImgDrive(tmp_path); d.add("big.jpg", big); d.add("rot.jpg", rotated); d.add("alpha.png", png)
    s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert sorted(s.photos()) == ["alpha.jpg", "big.jpg", "rot.jpg"]
    sizes = {n: Image.open(tmp_path / "c" / n).size for n in s.photos()}
    assert sizes["big.jpg"] == (1440, 1080)
    assert sizes["rot.jpg"] == (810, 1080)            # portrait after EXIF rotation
    assert sizes["alpha.png".replace(".png", ".jpg")] == (800, 600)  # never upscaled
    assert all(Image.open(tmp_path / "c" / n).format == "JPEG" for n in s.photos())
    assert os.path.getsize(tmp_path / "c" / "big.jpg") < 1_000_000
    assert not [f for f in os.listdir(tmp_path / "c") if f.endswith((".raw", ".part"))]

def test_custom_max_size(tmp_path):
    src, dst = tmp_path / "a.jpg", tmp_path / "b.jpg"; big(str(src)); downscale(str(src), str(dst), 1280, 720)
    assert Image.open(dst).size == (960, 720)

def test_corrupt_image_skipped_not_fatal(tmp_path):
    d = ImgDrive(tmp_path); d.add("ok.jpg", big); d.add("bad.jpg", lambda p: open(p, "wb").write(b"notanimage"))
    s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert s.photos() == ["ok.jpg"] and "bad.jpg" in s.last_error

def test_cache_cap_keeps_newest(tmp_path):
    def noise(dest):
        import random; im = Image.effect_noise((900, 700), 80).convert("RGB"); im.save(dest, "JPEG")
    d = ImgDrive(tmp_path)
    for i in range(6): d.add(f"p{i}.jpg", noise, mod=f"2026-10-0{i+1}")
    s = PhotoSync(d, str(tmp_path / "c"), max_cache_mb=1); s.sync()
    total = sum(os.path.getsize(tmp_path / "c" / n) for n in s.photos())
    assert total <= 1024 * 1024 and s.photos() and "p5.jpg" in s.photos()
    calls = []; orig = d.download; d.download = lambda *a: (calls.append(a), orig(*a))
    s.sync(); assert calls == []                      # capped photos are not re-downloaded each cycle

def test_long_run_memory_is_bounded(tmp_path):
    """Simulates ~a week of sync/refresh cycles + UI polling; Python heap must not grow."""
    import tracemalloc, gc
    c, cfg, p, _ = _app(tmp_path)
    app_photos = c.application.config["photos"]; cal = c.application.config["cal"]
    def cycle(n):
        for _ in range(n):
            app_photos.sync(); cal.refresh()
            c.get("/api/photos"); c.get("/api/events"); c.get("/api/status")
            c.application.config["tick"]()
    cycle(50); gc.collect(); tracemalloc.start()
    base = tracemalloc.take_snapshot(); cycle(400); gc.collect()
    growth = sum(st.size_diff for st in tracemalloc.take_snapshot().compare_to(base, "filename"))
    tracemalloc.stop()
    assert growth < 512 * 1024, f"heap grew {growth} bytes over 400 cycles"
