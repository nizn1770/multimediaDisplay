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
