import datetime as dt, logging, os, time
from zoneinfo import ZoneInfo
import ipaddress
from flask import Flask, jsonify, send_from_directory, abort, request
from .config import load_config, calendars, save_local, validate_hours, local_path
from .clients import make_clients
from .services import PhotoSync, CalendarService, Background, in_night, ScreenController
STATIC = os.path.join(os.path.dirname(__file__), "static")

def create_app(cfg=None, drive=None, calendar=None, start_background=True, weather_fn=None, screen_runner=None, config_path=None):
    """drive/calendar: inject any objects implementing list_images/download and list_events."""
    cfg = cfg or load_config()
    if drive is None or calendar is None:
        d, c = make_clients(cfg); drive = drive or d; calendar = calendar or c
    tz = ZoneInfo(cfg["timezone"])
    sl = cfg["slideshow"]
    photos = PhotoSync(drive, cfg["drive"]["cache_dir"], sl.get("max_width", 1920), sl.get("max_height", 1080),
                       sl.get("jpeg_quality", 85), cfg["drive"].get("max_cache_mb", 500))
    cal = CalendarService(calendar, calendars(cfg), cfg["timezone"])
    weather = {"data": None, "ts": 0}
    w_cfg = cfg["weather"]
    def fetch_weather():
        if weather_fn: return weather_fn()
        if cfg["mock"]:
            t = dt.date.today()
            return {"temp": 48, "code": 2, "high": 54, "low": 39, "location": w_cfg.get("location_name"),
                    "forecast": [{"date": (t + dt.timedelta(days=i)).isoformat(), "high": 54 - i * 3, "low": 39 - i * 2,
                                  "code": [2, 61, 3][i % 3]} for i in range(w_cfg.get("forecast_days", 3))]}
        import requests
        w = cfg["weather"]
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": w["latitude"], "longitude": w["longitude"], "current_weather": "true",
            "daily": "temperature_2m_max,temperature_2m_min,weathercode", "forecast_days": w.get("forecast_days", 3), "temperature_unit": w["units"],
            "timezone": cfg["timezone"]}).json()
        return {"temp": r["current_weather"]["temperature"], "code": r["current_weather"]["weathercode"],
                "high": r["daily"]["temperature_2m_max"][0], "low": r["daily"]["temperature_2m_min"][0],
                "location": w.get("location_name"),
                "forecast": [{"date": d, "high": hi, "low": lo, "code": c} for d, hi, lo, c in zip(
                    r["daily"]["time"], r["daily"]["temperature_2m_max"], r["daily"]["temperature_2m_min"], r["daily"]["weathercode"])]}
    cfg_file = config_path or local_path()
    mt = {"m": os.path.getmtime(cfg_file) if os.path.exists(cfg_file) else None}
    def reload_cfg():
        """Pick up external edits (e.g. ./pitv set-hours) to live-tunable sections without restart."""
        m = os.path.getmtime(cfg_file) if os.path.exists(cfg_file) else None
        if m == mt["m"]: return
        mt["m"] = m
        try:
            new = load_config(cfg_file)
            validate_hours(new["night"]["on_at"], new["night"]["off_at"])
        except Exception as e:
            logging.warning("config reload ignored: %s", e); return
        for k in ("night", "settings", "slideshow"): cfg[k] = new[k]
        logging.info("config reloaded")
    def tick():
        reload_cfg(); return screen.tick()
    screen = ScreenController(lambda: cfg, tz, screen_runner)
    control = {"seq": 0, "action": None, "paused": False}
    app = Flask(__name__, static_folder=None)
    app.config.update(PITV=cfg, photos=photos, cal=cal, screen=screen, tick=tick)
    if start_background:
        bg = Background()
        bg.every(cfg["drive"]["sync_interval_sec"], photos.sync)
        bg.every(cfg["calendar"]["refresh_interval_sec"], cal.refresh)
        bg.every(30, tick)
    else:
        photos.sync(); cal.refresh()

    @app.get("/")
    def index(): return send_from_directory(STATIC, "index.html")
    @app.get("/static/<path:p>")
    def static_(p): return send_from_directory(STATIC, p)
    @app.get("/photos/<name>")
    def photo(name):
        if name not in photos.photos(): abort(404)
        return send_from_directory(os.path.abspath(photos.cache), name, max_age=86400)
    @app.get("/api/photos")
    def api_photos():
        names = photos.photos()
        return jsonify(photos=names, versions={n: photos.version(n) for n in names}, skipped=len(photos.skipped), interval=cfg["slideshow"]["seconds_per_photo"],
                       last_sync=photos.last_sync, offline=photos.offline, error=photos.last_error, warnings=photos.warnings)
    @app.get("/api/events")
    def api_events():
        return jsonify(events=cal.events, by_day={k: [e["id"] for e in v] for k, v in cal.by_day().items()},
                       today=dt.datetime.now(tz).date().isoformat(), agenda=cal.agenda(),
                       calendars=cal.cals, last_fetch=cal.last_fetch, offline=cal.offline, error=cal.last_error, warnings=cal.warnings)
    @app.get("/api/status")
    def api_status():
        reload_cfg(); now = dt.datetime.now(tz); n = cfg["night"]
        night = bool(n["enabled"] and in_night(now, n["off_at"], n["on_at"]))
        w = None
        if cfg["weather"]["enabled"]:
            if time.time() - weather["ts"] > 900:
                try: weather["data"] = fetch_weather()
                except Exception as e: logging.warning("weather: %s", e)
                weather["ts"] = time.time()
            w = weather["data"]
        return jsonify(now=now.isoformat(), timezone=cfg["timezone"], night=night, weather=w, mock=cfg["mock"],
                       control=control, hours={"on_at": n["on_at"], "off_at": n["off_at"], "enabled": n["enabled"]})

    def body():
        b = request.get_json(silent=True)
        if b is None: b = {}
        if not isinstance(b, dict): abort(400, description="JSON body must be an object")
        return b
    def lan_only():
        try:
            ip = ipaddress.ip_address(request.remote_addr or "")
        except ValueError:
            abort(403)
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            abort(403)
        pin = str(cfg.get("settings", {}).get("pin") or "")
        if pin and request.method == "POST":
            given = body().get("pin") or request.headers.get("X-PIN", "")
            if str(given) != pin:
                abort(401)
    @app.get("/settings")
    def settings_page():
        lan_only(); return send_from_directory(STATIC, "settings.html")
    @app.get("/api/settings")
    def get_settings():
        lan_only(); n = cfg["night"]
        return jsonify(on_at=n["on_at"], off_at=n["off_at"], enabled=n["enabled"],
                       pin_required=bool(cfg.get("settings", {}).get("pin")), control=control)
    @app.post("/api/settings")
    def post_settings():
        lan_only(); b = body()
        on_at, off_at = b.get("on_at", cfg["night"]["on_at"]), b.get("off_at", cfg["night"]["off_at"])
        enabled = b.get("enabled", cfg["night"]["enabled"])
        try:
            validate_hours(on_at, off_at)
            if not isinstance(enabled, bool): raise ValueError("enabled must be true/false")
        except ValueError as e:
            return jsonify(error=str(e)), 400
        upd = {"night": {"on_at": on_at, "off_at": off_at, "enabled": enabled}}
        save_local(upd, cfg_file); mt["m"] = os.path.getmtime(cfg_file)
        cfg["night"].update(upd["night"]); screen.tick()   # live, no restart
        return jsonify(ok=True, **upd["night"])
    ACTIONS = {"next", "prev", "pause", "resume", "photos", "week", "month"}
    @app.post("/api/control")
    def post_control():
        lan_only(); a = body().get("action")
        if a not in ACTIONS: return jsonify(error=f"action must be one of {sorted(ACTIONS)}"), 400
        if a in ("pause", "resume"): control["paused"] = a == "pause"
        control["seq"] += 1; control["action"] = a
        return jsonify(ok=True, control=control)
    @app.errorhandler(400)
    def bad_request(e): return jsonify(error=getattr(e, "description", "bad request")), 400
    @app.get("/healthz")
    def health(): return "ok"
    return app

def main():
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    create_app(cfg).run(host=cfg["server"]["host"], port=cfg["server"]["port"], threaded=True)

if __name__ == "__main__":
    main()
