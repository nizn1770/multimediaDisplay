import datetime as dt, json, logging, os, threading, time
from zoneinfo import ZoneInfo
log = logging.getLogger("pitv")

def downscale(src, dest, max_w=1920, max_h=1080, quality=85):
    """Fix EXIF orientation, shrink to fit max_w x max_h, save as progressive JPEG (never upscales)."""
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (0, 0, 0))
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1]); im = bg
        im.thumbnail((max_w, max_h), Image.LANCZOS)
        im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)

class PhotoSync:
    """Mirrors Drive folder into cache_dir. Atomic writes; removed files are pruned;
    failures keep the existing cache (offline-safe)."""
    def __init__(self, drive, cache_dir, max_w=1920, max_h=1080, quality=85, max_cache_mb=500):
        self.drive, self.cache = drive, cache_dir
        self.max_w, self.max_h, self.quality, self.max_bytes = max_w, max_h, quality, max_cache_mb * 1024 * 1024
        os.makedirs(cache_dir, exist_ok=True)
        self.manifest_path = os.path.join(cache_dir, ".manifest.json")
        self.manifest = json.load(open(self.manifest_path)) if os.path.exists(self.manifest_path) else {}
        self.last_error, self.last_sync = None, None
        self.lock = threading.Lock()
    @staticmethod
    def local_name(f):
        fid = os.path.splitext(f["id"].replace("/", "_"))[0]
        return fid + ".jpg"   # everything is re-encoded to JPEG
    def sync(self):
        with self.lock:
            try:
                files = self.drive.list_images()
            except Exception as e:
                self.last_error = f"list failed: {e}"; log.warning(self.last_error); return False
            seen = {}
            for f in files:
                name = self.local_name(f)
                seen[name] = f.get("modifiedTime")
                dest = os.path.join(self.cache, name)
                if self.manifest.get(name) == "__capped__" or (self.manifest.get(name) == seen[name] and os.path.exists(dest)):
                    if self.manifest.get(name) == "__capped__": seen[name] = "__capped__"
                    continue
                tmp = dest + ".part"
                try:
                    raw = tmp + ".raw"
                    try:
                        self.drive.download(f["id"], raw)
                        downscale(raw, tmp, self.max_w, self.max_h, self.quality)
                    finally:
                        if os.path.exists(raw): os.remove(raw)
                    os.replace(tmp, dest)
                    self.manifest[name] = seen[name]
                except Exception as e:
                    self.last_error = f"download {f['name']} failed: {e}"; log.warning(self.last_error)
                    if os.path.exists(tmp): os.remove(tmp)
                    seen.pop(name, None)
                    if os.path.exists(dest): seen[name] = self.manifest.get(name)
            for name in list(self.manifest):
                if name not in seen:
                    self.manifest.pop(name)
                    try: os.remove(os.path.join(self.cache, name))
                    except FileNotFoundError: pass
            self._enforce_cap(files)
            json.dump(self.manifest, open(self.manifest_path + ".tmp", "w"))
            os.replace(self.manifest_path + ".tmp", self.manifest_path)
            self.last_sync = time.time()
            if files is not None and self.last_error and self.last_error.startswith("list"): self.last_error = None
            return True
    def _enforce_cap(self, files):
        """Keep newest photos (by Drive modifiedTime) within max_cache_mb; drop the oldest."""
        order = {self.local_name(f): f.get("modifiedTime") or "" for f in files}
        names = sorted(self.photos(), key=lambda n: order.get(n, ""), reverse=True)
        total = 0
        for n in names:
            p = os.path.join(self.cache, n); sz = os.path.getsize(p)
            if total + sz > self.max_bytes:
                os.remove(p); self.manifest[n] = "__capped__"   # don't re-download every cycle
            else:
                total += sz
    def photos(self):
        return sorted(n for n in os.listdir(self.cache) if n.endswith(".jpg") and not n.startswith("."))

def _parse(t, tz):
    if "date" in t:
        return dt.date.fromisoformat(t["date"]), True
    return dt.datetime.fromisoformat(t["dateTime"].replace("Z", "+00:00")).astimezone(tz), False

class CalendarService:
    """Fetches events for a window, normalises to local tz. Keeps last good data on error."""
    def __init__(self, cal, calendar_ids, tzname):
        self.cal, self.tz = cal, ZoneInfo(tzname)
        self.cals = [c if isinstance(c, dict) else {"id": c, "name": c, "color": "#4a90e2"} for c in calendar_ids]
        self.ids = [c["id"] for c in self.cals]
        self.color = {c["id"]: c["color"] for c in self.cals}
        self.events, self.last_error, self.last_fetch = [], None, None
    def refresh(self, today=None):
        today = today or dt.datetime.now(self.tz).date()
        start = dt.datetime.combine(today.replace(day=1) - dt.timedelta(days=7), dt.time(), self.tz)
        end = start + dt.timedelta(days=50)
        try:
            raw = []
            for cid in self.ids:
                raw += [(cid, e) for e in self.cal.list_events(cid, start, end)]
        except Exception as e:
            self.last_error = str(e); log.warning("calendar: %s", e); return False
        evs = []
        for cid, e in raw:
            if e.get("status") == "cancelled": continue
            s, allday = _parse(e["start"], self.tz)
            en, _ = _parse(e["end"], self.tz)
            evs.append({"id": e.get("id"), "calendar": cid, "color": self.color.get(cid), "title": e.get("summary", "(no title)"),
                        "all_day": allday, "start": s.isoformat(), "end": en.isoformat()})
        evs.sort(key=lambda x: (x["start"][:10], not x["all_day"], x["start"]))
        self.events, self.last_error, self.last_fetch = evs, None, time.time()
        return True
    def days_for(self, ev):
        """Local dates an event covers (all-day end is exclusive; timed end at 00:00 exclusive)."""
        if ev["all_day"]:
            s, e = dt.date.fromisoformat(ev["start"]), dt.date.fromisoformat(ev["end"])
            e = e - dt.timedelta(days=1)
        else:
            s = dt.datetime.fromisoformat(ev["start"]).date()
            ed = dt.datetime.fromisoformat(ev["end"])
            e = (ed - dt.timedelta(microseconds=1)).date() if ed > dt.datetime.fromisoformat(ev["start"]) else s
        days, d = [], s
        while d <= max(s, e):
            days.append(d.isoformat()); d += dt.timedelta(days=1)
        return days
    def agenda(self, now=None, n=3):
        """Next n events that haven't ended (all-day events count for their whole day)."""
        now = now or dt.datetime.now(self.tz)
        out = []
        for ev in self.events:
            end = (dt.datetime.combine(dt.date.fromisoformat(ev["end"]), dt.time(), self.tz) if ev["all_day"]
                   else dt.datetime.fromisoformat(ev["end"]))
            if end > now: out.append(ev)
        out.sort(key=lambda e: e["start"] if not e["all_day"] else e["start"] + "T00:00:00")
        return out[:n]
    def by_day(self):
        out = {}
        for ev in self.events:
            for d in self.days_for(ev):
                out.setdefault(d, []).append(ev)
        return out

def in_night(now, off, on):
    off, on = dt.time.fromisoformat(off), dt.time.fromisoformat(on)
    t = now.time()
    return (off <= t or t < on) if off > on else (off <= t < on)

class Background:
    def __init__(self): self.threads = []
    def every(self, sec, fn):
        def loop():
            while True:
                try: fn()
                except Exception: log.exception("bg task")
                time.sleep(sec)
        t = threading.Thread(target=loop, daemon=True); t.start(); self.threads.append(t)

class ScreenController:
    """Turns the physical display on/off based on live config (checked every tick)."""
    def __init__(self, cfg_getter, tz, runner=None):
        self.cfg, self.tz, self.state = cfg_getter, tz, None
        self.runner = runner or self._run
    def _run(self, mode):
        import subprocess
        cmd = self.cfg()["night"].get("screen_command", "./scripts/screen.sh")
        root = os.path.join(os.path.dirname(__file__), "..")
        subprocess.run([cmd, mode], cwd=root, timeout=30, check=False)
    def tick(self, now=None):
        n = self.cfg()["night"]
        now = now or dt.datetime.now(self.tz)
        want = "off" if (n.get("enabled") and in_night(now, n["off_at"], n["on_at"])) else "on"
        if not n.get("control_display", True):
            return want
        if want != self.state:
            try: self.runner(want); self.state = want
            except Exception as e: log.warning("screen %s failed: %s", want, e)
        return want
