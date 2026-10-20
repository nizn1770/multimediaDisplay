import datetime as dt, json, logging, os, threading, time
from zoneinfo import ZoneInfo
log = logging.getLogger("pitv")

class PhotoSync:
    """Mirrors Drive folder into cache_dir. Atomic writes; removed files are pruned;
    failures keep the existing cache (offline-safe)."""
    def __init__(self, drive, cache_dir):
        self.drive, self.cache = drive, cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.manifest_path = os.path.join(cache_dir, ".manifest.json")
        self.manifest = json.load(open(self.manifest_path)) if os.path.exists(self.manifest_path) else {}
        self.last_error, self.last_sync = None, None
        self.lock = threading.Lock()
    @staticmethod
    def local_name(f):
        ext = os.path.splitext(f["name"])[1].lower() or ".jpg"
        fid = f["id"].replace("/", "_")
        return fid if fid.lower().endswith(ext) else fid + ext
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
                if self.manifest.get(name) == seen[name] and os.path.exists(dest):
                    continue
                tmp = dest + ".part"
                try:
                    self.drive.download(f["id"], tmp); os.replace(tmp, dest)
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
            json.dump(self.manifest, open(self.manifest_path + ".tmp", "w"))
            os.replace(self.manifest_path + ".tmp", self.manifest_path)
            self.last_sync = time.time()
            if files is not None and self.last_error and self.last_error.startswith("list"): self.last_error = None
            return True
    def photos(self):
        return sorted(n for n in os.listdir(self.cache) if not n.startswith(".") and not n.endswith(".part"))

def _parse(t, tz):
    if "date" in t:
        return dt.date.fromisoformat(t["date"]), True
    return dt.datetime.fromisoformat(t["dateTime"].replace("Z", "+00:00")).astimezone(tz), False

class CalendarService:
    """Fetches events for a window, normalises to local tz. Keeps last good data on error."""
    def __init__(self, cal, calendar_ids, tzname):
        self.cal, self.ids, self.tz = cal, calendar_ids, ZoneInfo(tzname)
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
            evs.append({"id": e.get("id"), "calendar": cid, "title": e.get("summary", "(no title)"),
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
