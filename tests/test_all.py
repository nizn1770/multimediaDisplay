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
    assert s.photos() == ["ok.jpg"] and "bad.jpg" in " ".join(s.warnings) and not s.offline and s.last_error is None

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

# ---- QA iteration-5 regressions ----
from app.config import calendars
import json as _json

def test_qa1_legacy_calendar_ids_win(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text("calendar:\n  calendar_ids: [fam, work]\n")
    assert [c["id"] for c in calendars(load_config(str(p)))] == ["fam", "work"]
    p.write_text("calendar:\n  calendars:\n    - id: x\n")
    assert [c["id"] for c in calendars(load_config(str(p)))] == ["x"]

def test_qa2_huge_jpeg_decoded_with_draft_low_rss(tmp_path):
    src = tmp_path / "huge.jpg"
    subprocess.run([sys.executable, "-c", f"from PIL import Image; Image.new('RGB',(8000,6000),(9,99,199)).save(r'{src}',quality=90)"], check=True)
    code = f"""
import resource, sys; sys.path.insert(0, r'{ROOT}')
from app.services import downscale
from PIL import Image
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
downscale(r'{src}', r'{tmp_path / "out.jpg"}')
print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before, Image.open(r'{tmp_path / "out.jpg"}').size)
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split(maxsplit=1)
    assert int(out[0]) < 60 * 1024, f"RSS grew {int(out[0])//1024} MB"   # full decode would be ~144 MB+
    assert out[1].strip() == "(1440, 1080)"

def _git(cwd, *a): return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

def _deploy_env(tmp_path, health_ok):
    """origin bare repo + a 'Pi' clone of this repo's scripts; restart/health are faked."""
    origin, pi = tmp_path / "origin.git", tmp_path / "pi"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "work"; work.mkdir()
    _git(work, "init", "-q", "-b", "main"); _git(work, "config", "user.email", "t@t"); _git(work, "config", "user.name", "t")
    (work / "scripts").mkdir(); shutil.copy(os.path.join(ROOT, "scripts", "update.sh"), work / "scripts")
    (work / "requirements.txt").write_text(""); (work / "v").write_text("1")
    (work / "pitv").write_text("#!/bin/sh\necho 1\n"); os.chmod(work / "pitv", 0o755)
    _git(work, "add", "-A"); _git(work, "commit", "-qm", "v1"); _git(work, "remote", "add", "origin", str(origin)); _git(work, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(pi)], check=True)
    (pi / ".venv" / "bin").mkdir(parents=True)
    pip = pi / ".venv" / "bin" / "pip"; pip.write_text('#!/bin/sh\n[ -f "$PWD/fail_pip" ] && exit 1; exit 0\n'); os.chmod(pip, 0o755)
    env = {**os.environ, "PITV_RESTART_CMD": "true", "PITV_HEALTH_TRIES": "1", "PITV_PORT": "1" if not health_ok else "0"}
    return work, pi, env

def _commit(work, name, txt):
    (work / name).write_text(txt); _git(work, "add", "-A"); _git(work, "commit", "-qm", txt); _git(work, "push", "-q", "origin", "main")
    return _git(work, "rev-parse", "HEAD")

def _update(pi, env):
    return subprocess.run(["bash", "scripts/update.sh"], cwd=pi, env=env, capture_output=True, text=True)

def _fail_once_curl(tmp_path, env):
    """curl shim: first health probe (new commit) fails, later ones (rollback) pass."""
    shim = tmp_path / "once"; shim.mkdir(exist_ok=True); flag = tmp_path / "curl_ok"
    (shim / "curl").write_text(f'#!/bin/sh\n[ -f "{flag}" ] && exit 0; touch "{flag}"; exit 1\n'); os.chmod(shim / "curl", 0o755)
    return {**env, "PATH": f"{shim}:{env['PATH']}"}, flag

def test_qa3_bad_commit_recorded_and_skipped(tmp_path):
    work, pi, env = _deploy_env(tmp_path, health_ok=False)
    env, _ = _fail_once_curl(tmp_path, env)
    old = _git(pi, "rev-parse", "HEAD"); bad = _commit(work, "v", "2")
    r = _update(pi, env); assert r.returncode != 0
    assert _git(pi, "rev-parse", "HEAD") == old and (pi / ".pitv-bad-commit").read_text().strip() == bad
    r = _update(pi, env); assert r.returncode == 0 and "skipping" in r.stdout and _git(pi, "rev-parse", "HEAD") == old
    # origin moves past the bad commit -> retried; with a healthy server it deploys and clears the marker
    good = _commit(work, "v", "3")
    env_ok = {**env, "PITV_HEALTH_TRIES": "1"}
    # fake healthy server via curl shim
    shim = tmp_path / "bin"; shim.mkdir(); (shim / "curl").write_text("#!/bin/sh\nexit 0\n"); os.chmod(shim / "curl", 0o755)
    env_ok["PATH"] = f"{shim}:{env['PATH']}"
    r = _update(pi, env_ok); assert r.returncode == 0, r.stderr
    assert _git(pi, "rev-parse", "HEAD") == good and not (pi / ".pitv-bad-commit").exists()

def test_qa4_pip_failure_rolls_back(tmp_path):
    work, pi, env = _deploy_env(tmp_path, health_ok=True)
    old = _git(pi, "rev-parse", "HEAD"); (pi / "fail_pip").write_text("1")
    _commit(work, "requirements.txt", "flask\n")
    r = _update(pi, env); assert r.returncode != 0 and "rolling back" in r.stderr
    assert _git(pi, "rev-parse", "HEAD") == old
    r = _update(pi, env); assert "up to date" not in r.stdout   # not silently 'up to date'

def test_qa5_unsupported_and_broken_recorded_as_skipped(tmp_path):
    d = ImgDrive(tmp_path); d.add("ok.jpg", big)
    d.add("clip.mov", lambda p: open(p, "wb").write(b"x"))
    d.add("bad.jpg", lambda p: open(p, "wb").write(b"notanimage"))
    d.files["clip.mov"] = (d.files["clip.mov"][0], "1")
    real_list = d.list_images
    d.list_images = lambda: [dict(f, mimeType="video/quicktime") if f["id"] == "clip.mov" else f for f in real_list()]
    s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert s.photos() == ["ok.jpg"] and sorted(s.skipped) == ["bad.jpg", "clip.jpg"]
    calls = []; orig = d.download; d.download = lambda *a: (calls.append(a[0]), orig(*a))
    s.sync(); assert calls == []                       # skipped files not re-downloaded
    assert s.last_error is None                        # cleared after a clean sync (qa15)

def test_qa5_heic_supported(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    def heic(dest):
        Image.new("RGB", (3000, 2000), (1, 2, 3)).save(dest, format="HEIF")
    d = ImgDrive(tmp_path); d.add("IMG_1.HEIC", heic)
    d.list_images = (lambda real: lambda: [dict(f, mimeType="image/heic") for f in real()])(d.list_images)
    s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert s.photos() == ["IMG_1.jpg"] and Image.open(tmp_path / "c" / "IMG_1.jpg").size == (1620, 1080)

def test_qa6_capped_photos_return_when_space_frees(tmp_path):
    def noise(dest): Image.effect_noise((900, 700), 80).convert("RGB").save(dest, "JPEG")
    d = ImgDrive(tmp_path)
    for i in range(6): d.add(f"p{i}.jpg", noise, mod=f"2026-10-0{i+1}")
    s = PhotoSync(d, str(tmp_path / "c"), max_cache_mb=1); s.sync()
    before = set(s.photos()); assert "p0.jpg" not in before
    for n in before: del d.files[n.replace(".jpg", ".jpg")]
    s.sync(); after = set(s.photos())
    assert after and not (after & before) and after <= {f"p{i}.jpg" for i in range(6)}  # previously capped ones came back

def test_qa7_malformed_events_skipped_and_reported(tmp_path):
    ev = [{"id": "nostart", "end": {"date": "2026-10-21"}}, {"id": "noend", "start": {"date": "2026-10-21"}},
          {"id": "garbage", "start": {"dateTime": "not-a-date"}, "end": {"dateTime": "x"}},
          {"id": "ok", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}}]
    c = CalendarService(FakeCal(ev), ["p"], "America/Chicago"); assert c.refresh(dt.date(2026, 10, 20))
    assert [e["id"] for e in c.events] == ["ok"] and "3" in " ".join(c.warnings) and not c.offline
    cfg = load_config("/nonexistent"); cfg["drive"]["cache_dir"] = str(tmp_path)
    app = create_app(cfg, drive=FakeDrive(FIX), calendar=FakeCal(ev), start_background=False).test_client()
    j = app.get("/api/events").get_json(); assert j["warnings"] and j["offline"] is False and j["error"] is None

def test_qa8_scripts_read_port_from_config(tmp_path):
    for f in ("scripts/update.sh", "scripts/kiosk.sh"):
        txt = open(os.path.join(ROOT, f)).read()
        assert "pitv get server.port" in txt and "127.0.0.1:8080" not in txt
    p = tmp_path / "c.yaml"; p.write_text("server:\n  port: 9123\n")
    r = subprocess.run([os.path.join(ROOT, "pitv"), "get", "server.port"], env={**os.environ, "PITV_CONFIG": str(p)}, capture_output=True, text=True)
    assert r.stdout.strip() == "9123"

def test_qa9_screen_sh_cec_first_then_xrandr(tmp_path):
    shim = tmp_path / "bin"; shim.mkdir(); log = tmp_path / "log"
    for name in ("cec-client", "xrandr", "timeout"):
        body = '#!/bin/sh\nshift; exec "$@"\n' if name == "timeout" else f'#!/bin/sh\necho "{name} $* $(cat 2>/dev/null)" >> {log}\n'
        (shim / name).write_text(body); os.chmod(shim / name, 0o755)
    env = {**os.environ, "PATH": f"{shim}:/usr/bin:/bin"}
    subprocess.run(["bash", os.path.join(ROOT, "scripts", "screen.sh"), "off"], env=env, check=True, capture_output=True)
    lines = log.read_text().splitlines()
    assert lines[0].startswith("cec-client") and "standby 0" in lines[0]
    assert any(l.startswith("xrandr --output HDMI-1 --off") for l in lines)
    log.unlink(); subprocess.run(["bash", os.path.join(ROOT, "scripts", "screen.sh"), "on"], env=env, check=True, capture_output=True)
    assert "on 0" in log.read_text()
    assert subprocess.run(["bash", os.path.join(ROOT, "scripts", "screen.sh"), "bogus"], env=env).returncode == 2
    assert "cec-utils" in open(os.path.join(ROOT, "install.sh")).read()

def test_qa10_mask_hides_all_ids(tmp_path):
    from app.cli import mask
    c = {"calendar": {"calendar_ids": ["abc123@" + "group.calendar.google.com"], "calendars": [{"id": "x@" + "gmail.com", "name": "Fam"}]},
         "settings": {"pin": "0123"}, "drive": {"folder_id": "1" + "Z" * 32}, "misc": "pitv" + "@p.iam.gserviceaccount.com"}
    out = _json.dumps(mask(c))
    for secret in ("abc123@", "x@gmail", "0123", "Z" * 10, "pitv@"): assert secret not in out
    assert "Fam" in out

def test_qa12_install_uses_profile_not_bash_profile():
    txt = open(os.path.join(ROOT, "install.sh")).read()
    assert 'PROFILE="$HOME_DIR/.profile"' in txt and 'cat >>"$HOME_DIR/.bash_profile"' not in txt

@pytest.mark.parametrize("text", ["id: 0B" + "x1Y2" * 7, "id: 1" + "a" * 43, "cal: someone" + "@gmail.com",
                                  "real abc" + "@group.calendar.google.com # example", "example 1" + "Q" * 32])
def test_qa13_scanner_tightened(text):
    assert cs.scan_text(text, "x")

def test_qa14_pin_octal_and_non_object_json(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text("settings:\n  pin: 0123\n")
    assert load_config(str(p))["settings"]["pin"] == "0123"
    p.write_text("settings:\n  pin: 4321\n"); assert load_config(str(p))["settings"]["pin"] == "4321"
    c, _, _, _ = _app(tmp_path, pin="1")
    for b in ([1, 2], "str", 5):
        assert c.post("/api/settings", json=b).status_code == 400
        assert c.post("/api/control", json=b).status_code == 400

def test_qa15_versions_dedupe_naive_tz_mock_dst(tmp_path):
    c, _, _, _ = _app(tmp_path)
    p = c.get("/api/photos").get_json(); assert set(p["versions"]) == set(p["photos"]) and all(p["versions"].values())
    ev = [{"id": "a", "iCalUID": "u1", "start": {"dateTime": "2026-10-21T09:00:00"}, "end": {"dateTime": "2026-10-21T10:00:00"}},
          {"id": "b", "iCalUID": "u1", "start": {"dateTime": "2026-10-21T09:00:00"}, "end": {"dateTime": "2026-10-21T10:00:00"}},
          {"id": "lon", "start": {"dateTime": "2026-10-21T09:00:00", "timeZone": "Europe/London"}, "end": {"dateTime": "2026-10-21T10:00:00", "timeZone": "Europe/London"}}]
    class Two(FakeCal):
        def list_events(self, cid, *a): return [e for e in self.events if (cid == "c1") == (e["id"] != "b")]
    s = CalendarService(Two(ev), ["c1", "c2"], "America/Chicago"); s.refresh(dt.date(2026, 10, 20))
    by = {e["id"]: e for e in s.events}
    assert "b" not in by                                         # dupe across calendars removed
    assert by["a"]["start"].startswith("2026-10-21T09:00:00-05:00")  # naive -> configured tz (CDT)
    assert by["lon"]["start"].startswith("2026-10-21T03:00:00-05:00")  # naive + event timeZone
    from app.clients import MockCalendar
    mc = MockCalendar(tz="America/Chicago")
    offs = {e["start"]["dateTime"][-6:] for e in mc.list_events("p", None, None) if "dateTime" in e["start"] and e["id"] != "e6"}
    want = dt.datetime.now(ZoneInfo("America/Chicago")).strftime("%z"); want = want[:3] + ":" + want[3:]
    assert offs <= {"-05:00", "-06:00"} and offs   # real DST-aware offsets, not hard-coded
    assert "/config.local.yaml" in open(os.path.join(ROOT, "deploy", "pitv.service")).read()

# ---- QA iteration-6 regressions ----
from app.services import OversizedImage, DECODE_LIMITS
MEM_CAP_MB = 120

def _mk(path, code):
    subprocess.run([sys.executable, "-c", "from PIL import Image\nimport pillow_heif; pillow_heif.register_heif_opener()\n" + code.replace("OUT", repr(str(path)))], check=True)

def _measure(path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "measure_decode.py"), str(path)], capture_output=True, text=True, check=True)
    return _json.loads(r.stdout.strip().splitlines()[-1])

MEM_CASES = {
    "baseline_48mp.jpg": ("Image.new('RGB',(8000,6000),(9,99,199)).save(OUT, quality=90)", "1440x1080"),
    "progressive_48mp.jpg": ("Image.new('RGB',(8000,6000),(9,99,199)).save(OUT, progressive=True)", "oversized"),
    "progressive_108mp.jpg": ("Image.new('RGB',(12000,9000),(9,99,199)).save(OUT, progressive=True)", "oversized"),
    "progressive_12mp.jpg": ("Image.new('RGB',(4000,3000),(9,99,199)).save(OUT, progressive=True)", "1440x1080"),
    "heic_12mp.heic": ("Image.new('RGB',(4000,3000),(9,99,199)).save(OUT, format='HEIF')", "1440x1080"),
    "heic_48mp.heic": ("Image.new('RGB',(8000,6000),(9,99,199)).save(OUT, format='HEIF')", "oversized"),
    "png_16mp.png": ("Image.new('RGB',(4000,4000),(9,99,199)).save(OUT)", "1080x1080"),
}

@pytest.mark.parametrize("name", sorted(MEM_CASES))
def test_qa6_decode_memory_cap(tmp_path, name):
    pytest.importorskip("pillow_heif")
    code, expect = MEM_CASES[name]; p = tmp_path / name; _mk(p, code)
    m = _measure(p)
    assert m["result"].startswith(expect), m
    assert m["peak_mb"] < MEM_CAP_MB, f"{name}: peak {m['peak_mb']} MB ({m})"

def test_qa6_oversized_uses_drive_thumbnail(tmp_path):
    class ThumbDrive(ImgDrive):
        def __init__(s, t): super().__init__(t); s.thumbs, s.downloads = [], []
        def download(s, fid, dest): s.downloads.append(fid); super().download(fid, dest)
        def thumbnail(s, fid, dest, size): s.thumbs.append((fid, size)); Image.new("RGB", (size, size * 3 // 4)).save(dest, "JPEG")
    big_prog = lambda d: Image.new("RGB", (6000, 4000)).save(d, "JPEG", progressive=True)   # 24 MP progressive
    d = ThumbDrive(tmp_path); d.add("prog.jpg", big_prog); d.add("meta.jpg", big)
    real = d.list_images   # meta.jpg advertises its size -> thumbnail fetched without downloading original
    d.list_images = lambda: [dict(f, imageMediaMetadata={"width": 9000, "height": 6000}) if f["id"] == "meta.jpg" else f for f in real()]
    s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert s.photos() == ["meta.jpg", "prog.jpg"] and d.downloads == ["prog.jpg"]
    assert sorted(t[0] for t in d.thumbs) == ["meta.jpg", "prog.jpg"] and all(t[1] == 1920 for t in d.thumbs)
    assert Image.open(tmp_path / "c" / "prog.jpg").size == (1440, 1080)

def test_qa6_oversized_without_thumbnail_skipped_with_warning(tmp_path):
    d = ImgDrive(tmp_path); d.add("prog.jpg", lambda p: Image.new("RGB", (6000, 4000)).save(p, "JPEG", progressive=True))
    s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert s.photos() == [] and "prog.jpg" in s.skipped and "decode budget" in " ".join(s.warnings) and not s.offline

def test_qa6_max_image_pixels_set(tmp_path):
    from PIL import Image as I
    src = tmp_path / "a.jpg"; big(str(src)); downscale(str(src), str(tmp_path / "b.jpg"))
    assert I.MAX_IMAGE_PIXELS and I.MAX_IMAGE_PIXELS <= 200_000_000

def test_qa6_heic_orientation(tmp_path):
    pytest.importorskip("pillow_heif")
    src = tmp_path / "rot.heic"
    _mk(src, "im=Image.new('RGB',(4000,3000),(200,0,0)); ex=Image.Exif(); ex[0x0112]=6; im.save(OUT, format='HEIF', exif=ex.tobytes())")
    downscale(str(src), str(tmp_path / "o.jpg"))
    assert Image.open(tmp_path / "o.jpg").size == (810, 1080)   # rotated to portrait

def test_qa6_offline_vs_warnings_api(tmp_path):
    cfg = load_config("/nonexistent"); cfg["drive"]["cache_dir"] = str(tmp_path)
    d = ImgDrive(tmp_path); d.add("bad.jpg", lambda p: open(p, "wb").write(b"x"))
    ev = [{"id": "x", "start": {"date": "2026-10-20"}}]
    app = create_app(cfg, drive=d, calendar=FakeCal(ev), start_background=False).test_client()
    p, e = app.get("/api/photos").get_json(), app.get("/api/events").get_json()
    assert p["offline"] is False and p["warnings"] and p["error"] is None
    assert e["offline"] is False and e["warnings"] and e["error"] is None
    js = open(os.path.join(ROOT, "app", "static", "app.js")).read()
    assert "d.error" not in js and "offline" in js     # banner keyed on offline only
    cfg2 = load_config("/nonexistent"); cfg2["drive"]["cache_dir"] = str(tmp_path / "2")
    fd = FakeDrive(FIX); fd.fail = True; fc = FakeCal([]); fc.fail = True
    app2 = create_app(cfg2, drive=fd, calendar=fc, start_background=False).test_client()
    assert app2.get("/api/photos").get_json()["offline"] is True and app2.get("/api/events").get_json()["offline"] is True

@pytest.mark.parametrize("yaml_text,pin", [("settings: {pin: 0123}\n", "0123"), ("settings:\n  pin: 0000\n", "0000"),
    ("settings:\n  pin: 0123\n", "0123"), ("settings:\n  pin: 4321\n", "4321"), ("settings:\n  pin: '0042'\n", "0042")])
def test_qa6_pin_leading_zeros(tmp_path, yaml_text, pin):
    p = tmp_path / "c.yaml"; p.write_text(yaml_text); assert load_config(str(p))["settings"]["pin"] == pin

def test_qa6_rollback_health_checked_and_logged(tmp_path):
    work, pi, env = _deploy_env(tmp_path, health_ok=False)
    _commit(work, "v", "2"); r = _update(pi, env)
    assert r.returncode != 0 and "rollback:" in r.stderr and "NOT healthy" in r.stderr
    shim = tmp_path / "bin"; shim.mkdir(); (shim / "curl").write_text('#!/bin/sh\n[ -f "$HOME/ok" ] && exit 0; touch "$HOME/ok"; exit 1\n')
    os.chmod(shim / "curl", 0o755); home = tmp_path / "home"; home.mkdir()
    assert not (pi / ".pitv-bad-commit").exists()     # rollback also unhealthy -> env problem, no blacklist
    assert "ENVIRONMENT problem" in r.stderr
    env2 = {**env, "PATH": f"{shim}:{env['PATH']}", "HOME": str(home)}   # deploy health fails once, rollback health passes
    r = _update(pi, env2); assert r.returncode != 0 and "is healthy" in r.stderr

def test_qa6_update_warns_when_port_unreadable(tmp_path):
    work, pi, env = _deploy_env(tmp_path, health_ok=True)
    (pi / "pitv").write_text("#!/bin/sh\nexit 1\n"); env = {k: v for k, v in env.items() if k != "PITV_PORT"}
    r = _update(pi, env); assert "assuming 8080" in r.stderr

def test_qa6_mockdrive_unique_ids(tmp_path):
    from app.clients import MockDrive
    folder = tmp_path / "f"; folder.mkdir(); big(str(folder / "a.jpg")); png(str(folder / "a.png"))
    md = MockDrive(str(folder)); ids = [f["id"] for f in md.list_images()]
    assert len(set(ids)) == 2
    s = PhotoSync(md, str(tmp_path / "c")); s.sync(); assert len(s.photos()) == 2


# ---- post-signoff low items ----
def test_low1_animated_images_budget(tmp_path):
    def anim(size):
        def mk(dest):
            fr = [Image.new("RGB", size, (i * 40, 0, 0)) for i in range(4)]
            fr[0].save(dest, "WEBP", save_all=True, append_images=fr[1:], duration=100)
        return mk
    small = tmp_path / "s.webp"; anim((1600, 1200))(str(small)); downscale(str(small), str(tmp_path / "o.jpg"))
    assert Image.open(tmp_path / "o.jpg").size == (1440, 1080)
    bigp = tmp_path / "b.webp"; anim((4000, 4000))(str(bigp))
    with pytest.raises(OversizedImage): downscale(str(bigp), str(tmp_path / "o2.jpg"))
    m = _measure(bigp); assert m["result"].startswith("oversized") and m["peak_mb"] < MEM_CAP_MB

def test_low3_decompression_bomb_is_oversized_and_uses_thumbnail(tmp_path):
    bomb = lambda d: Image.new("1", (18000, 18000)).save(d, "PNG")   # 324 MP > Pillow's 2x limit
    p = tmp_path / "bomb.png"; bomb(str(p))
    with pytest.raises(OversizedImage): downscale(str(p), str(tmp_path / "o.jpg"))
    class TD(ImgDrive):
        def thumbnail(s, fid, dest, size): Image.new("RGB", (size, size)).save(dest, "JPEG")
    d = TD(tmp_path); d.add("bomb.png", bomb); s = PhotoSync(d, str(tmp_path / "c")); s.sync()
    assert s.photos() == ["bomb.jpg"]

def test_low2_env_problem_does_not_blacklist(tmp_path):
    work, pi, env = _deploy_env(tmp_path, health_ok=False)   # nothing ever healthy (broken env)
    _commit(work, "v", "2"); r = _update(pi, env)
    assert r.returncode != 0 and "ENVIRONMENT problem" in r.stderr and not (pi / ".pitv-bad-commit").exists()
    r = _update(pi, env); assert "skipping" not in r.stdout   # good commit retried next run

@pytest.mark.parametrize("txt,val", [("server:\n  port: 08080\n", 8080), ("server:\n  port: '9090'\n", 9090), ("server:\n  port: 8081\n", 8081)])
def test_low4_numeric_keys_coerced(tmp_path, txt, val):
    p = tmp_path / "c.yaml"; p.write_text(txt + "drive:\n  sync_interval_sec: 0300\n")
    c = load_config(str(p)); assert c["server"]["port"] == val and c["drive"]["sync_interval_sec"] == 300
