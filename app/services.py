import datetime as dt, hashlib, json, logging, os, threading, time
from zoneinfo import ZoneInfo
log = logging.getLogger("pitv")

try:  # HEIC/HEIF (iPhone photos); arm64 wheels exist for Pi OS Trixie/Bookworm
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:  # pragma: no cover
    HEIF = False

SUPPORTED_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"}
if HEIF:
    SUPPORTED_MIMES |= {"image/heic", "image/heif"}
_EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
             ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".heic": "image/heic", ".heif": "image/heif"}

def downscale(src, dest, max_w=1920, max_h=1080, quality=85):
    """Fix EXIF orientation, shrink to fit max_w x max_h, save JPEG. Never upscales.
    JPEGs are decoded at reduced scale via draft() so huge originals don't need full-res RAM."""
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        try:
            orient = im.getexif().get(0x0112, 1)
        except Exception:
            orient = 1
        req = (max_h, max_w) if orient in (5, 6, 7, 8) else (max_w, max_h)  # pre-rotation box
        if im.format == "JPEG":
            im.draft("RGB", req)          # DCT scaling: 8000x6000 decodes as 2000x1500
        im.thumbnail(req, Image.LANCZOS)  # shrink BEFORE rotate/convert to keep RAM low
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            rgba = im.convert("RGBA"); bg = Image.new("RGB", im.size, (0, 0, 0))
            bg.paste(rgba, mask=rgba.split()[-1]); im = bg
        im.thumbnail((max_w, max_h), Image.LANCZOS)
        im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)

class PhotoSync:
    """Mirrors a Drive folder into cache_dir, one image at a time.
    Manifest: name -> {mod, state: ok|capped|skipped, size, err}. Atomic writes; removed files pruned;
    unsupported/broken files are recorded as skipped (retried only if modified on Drive);
    cache size cap keeps the newest photos and re-admits capped ones when space frees up;
    Drive failures keep the existing cache (offline-safe)."""
    def __init__(self, drive, cache_dir, max_w=1920, max_h=1080, quality=85, max_cache_mb=500):
        self.drive, self.cache = drive, cache_dir
        self.max_w, self.max_h, self.quality, self.max_bytes = max_w, max_h, quality, max_cache_mb * 1024 * 1024
        os.makedirs(cache_dir, exist_ok=True)
        self.manifest_path = os.path.join(cache_dir, ".manifest.json")
        self.manifest = {}
        if os.path.exists(self.manifest_path):
            try:
                raw = json.load(open(self.manifest_path))
                for k, v in raw.items():  # migrate old {name: mod} format
                    self.manifest[k] = v if isinstance(v, dict) else {"mod": v, "state": "capped" if v == "__capped__" else "ok"}
            except Exception:
                log.warning("manifest unreadable; rebuilding")
        self.last_error, self.last_sync, self.skipped = None, None, []
        self.lock = threading.Lock()

    @staticmethod
    def local_name(f):
        return os.path.splitext(f["id"].replace("/", "_"))[0] + ".jpg"   # everything re-encoded to JPEG

    @staticmethod
    def mime_of(f):
        m = (f.get("mimeType") or "").lower()
        if m in ("", "application/octet-stream"):
            m = _EXT_MIME.get(os.path.splitext(f.get("name", ""))[1].lower(), m)
        return m

    def _fetch(self, f, name):
        dest = os.path.join(self.cache, name); tmp = dest + ".part"; raw = tmp + ".raw"
        try:
            self.drive.download(f["id"], raw)
            downscale(raw, tmp, self.max_w, self.max_h, self.quality)
            os.replace(tmp, dest)
            return os.path.getsize(dest)
        finally:
            for p in (raw, tmp):
                if os.path.exists(p): os.remove(p)

    def sync(self):
        with self.lock:
            try:
                files = self.drive.list_images()
            except Exception as e:
                self.last_error = f"Drive list failed: {e}"; log.warning(self.last_error); return False
            errors = []
            files = sorted(files, key=lambda f: f.get("modifiedTime") or "", reverse=True)  # newest first
            wanted = {}
            for f in files:
                name, mod = self.local_name(f), f.get("modifiedTime")
                wanted[name] = f
                ent = self.manifest.get(name)
                if ent and ent.get("mod") == mod and ent["state"] == "skipped":
                    continue
                if self.mime_of(f) not in SUPPORTED_MIMES:
                    self.manifest[name] = {"mod": mod, "state": "skipped", "err": f"unsupported type {self.mime_of(f)}"}
                    continue
                if ent and ent.get("mod") == mod and ent["state"] in ("ok", "capped") and \
                        (ent["state"] == "capped" or os.path.exists(os.path.join(self.cache, name))):
                    continue
                self.manifest[name] = {"mod": mod, "state": "pending"}
            # cache cap: newest-first; admit while it fits (capped ones are re-checked every sync)
            total = 0
            for f in files:
                name = self.local_name(f); ent = self.manifest[name]
                if ent["state"] == "skipped": continue
                path = os.path.join(self.cache, name)
                size = os.path.getsize(path) if ent["state"] == "ok" and os.path.exists(path) else ent.get("size")
                if size is not None and total + size > self.max_bytes:
                    if os.path.exists(path): os.remove(path)
                    ent.update(state="capped", size=size); continue
                if ent["state"] in ("pending", "capped") or not os.path.exists(path):
                    try:
                        size = self._fetch(f, name)
                    except Exception as e:
                        msg = f"{f.get('name', name)}: {e}"; errors.append(msg); log.warning("photo skipped: %s", msg)
                        self.manifest[name] = {"mod": f.get("modifiedTime"), "state": "skipped", "err": str(e)[:200]}
                        continue
                    if total + size > self.max_bytes:
                        os.remove(path); ent.update(state="capped", size=size); continue
                ent.update(state="ok", size=size); total += size
            for name in list(self.manifest):
                if name not in wanted:
                    self.manifest.pop(name)
                    try: os.remove(os.path.join(self.cache, name))
                    except FileNotFoundError: pass
            for n in os.listdir(self.cache):   # stray files (old formats, crashed temp files)
                if not n.startswith(".") and n not in self.manifest:
                    try: os.remove(os.path.join(self.cache, n))
                    except OSError: pass
            tmp = self.manifest_path + ".tmp"
            with open(tmp, "w") as fh: json.dump(self.manifest, fh)
            os.replace(tmp, self.manifest_path)
            self.skipped = [n for n, e in self.manifest.items() if e["state"] == "skipped"]
            self.last_sync = time.time()
            self.last_error = ("Some photos skipped: " + "; ".join(errors[:3])) if errors else None
            return True

    def photos(self):
        return sorted(n for n, e in self.manifest.items()
                      if e.get("state") == "ok" and os.path.exists(os.path.join(self.cache, n)))
    def version(self, name):
        e = self.manifest.get(name, {})
        return hashlib.sha1(f"{e.get('mod')}:{e.get('size')}".encode()).hexdigest()[:10]

def _parse(t, tz):
    """Google event time -> (date|aware datetime, all_day). Naive dateTimes use the event's timeZone, else tz."""
    if "date" in t:
        return dt.date.fromisoformat(t["date"]), True
    d = dt.datetime.fromisoformat(t["dateTime"].replace("Z", "+00:00"))
    if d.tzinfo is None:
        try: d = d.replace(tzinfo=ZoneInfo(t["timeZone"])) if t.get("timeZone") else d.replace(tzinfo=tz)
        except Exception: d = d.replace(tzinfo=tz)
    return d.astimezone(tz), False

class CalendarService:
    """Fetches events for a window, normalises to local tz, dedupes by iCalUID.
    Malformed events are skipped (and reported). Keeps last good data on fetch error."""
    def __init__(self, cal, calendar_ids, tzname):
        self.cal, self.tz = cal, ZoneInfo(tzname)
        self.cals = [c if isinstance(c, dict) else {"id": c, "name": c, "color": "#4a90e2"} for c in calendar_ids]
        self.ids = [c["id"] for c in self.cals]
        self.color = {c["id"]: c["color"] for c in self.cals}
        self.events, self.last_error, self.last_fetch, self.bad_events = [], None, None, 0
    def refresh(self, today=None):
        today = today or dt.datetime.now(self.tz).date()
        start = dt.datetime.combine(today.replace(day=1) - dt.timedelta(days=7), dt.time(), self.tz)
        end = start + dt.timedelta(days=50)
        try:
            raw = []
            for cid in self.ids:
                raw += [(cid, e) for e in (self.cal.list_events(cid, start, end) or [])]
        except Exception as e:
            self.last_error = f"Calendar fetch failed: {e}"; log.warning(self.last_error); return False
        evs, seen, bad = [], set(), 0
        for cid, e in raw:
            try:
                if e.get("status") == "cancelled": continue
                s, allday = _parse(e["start"], self.tz)
                en, _ = _parse(e["end"], self.tz)
                key = (e["iCalUID"], s.isoformat()) if e.get("iCalUID") else (cid, e.get("id"), s.isoformat())
                if key in seen: continue
                seen.add(key)
                evs.append({"id": e.get("id") or e.get("iCalUID") or f"ev{len(evs)}", "calendar": cid,
                            "color": self.color.get(cid), "title": e.get("summary") or "(no title)",
                            "all_day": allday, "start": s.isoformat(), "end": en.isoformat()})
            except Exception as ex:
                bad += 1; log.warning("skipping malformed event %r: %s", e.get("id") if isinstance(e, dict) else e, ex)
        evs.sort(key=lambda x: (x["start"][:10], not x["all_day"], x["start"]))
        self.events, self.last_fetch, self.bad_events = evs, time.time(), bad
        self.last_error = f"Skipped {bad} malformed event(s)" if bad else None
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
