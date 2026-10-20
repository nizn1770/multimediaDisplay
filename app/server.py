import datetime as dt, logging, os, time
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, send_from_directory, abort
from .config import load_config, calendars
from .clients import make_clients
from .services import PhotoSync, CalendarService, Background, in_night
STATIC = os.path.join(os.path.dirname(__file__), "static")

def create_app(cfg=None, drive=None, calendar=None, start_background=True, weather_fn=None):
    """drive/calendar: inject any objects implementing list_images/download and list_events."""
    cfg = cfg or load_config()
    if drive is None or calendar is None:
        d, c = make_clients(cfg); drive = drive or d; calendar = calendar or c
    tz = ZoneInfo(cfg["timezone"])
    photos = PhotoSync(drive, cfg["drive"]["cache_dir"])
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
    app = Flask(__name__, static_folder=None)
    app.config.update(PITV=cfg, photos=photos, cal=cal)
    if start_background:
        bg = Background()
        bg.every(cfg["drive"]["sync_interval_sec"], photos.sync)
        bg.every(cfg["calendar"]["refresh_interval_sec"], cal.refresh)
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
        return jsonify(photos=photos.photos(), interval=cfg["slideshow"]["seconds_per_photo"],
                       last_sync=photos.last_sync, error=photos.last_error)
    @app.get("/api/events")
    def api_events():
        return jsonify(events=cal.events, by_day={k: [e["id"] for e in v] for k, v in cal.by_day().items()},
                       today=dt.datetime.now(tz).date().isoformat(), agenda=cal.agenda(),
                       calendars=cal.cals, last_fetch=cal.last_fetch, error=cal.last_error)
    @app.get("/api/status")
    def api_status():
        now = dt.datetime.now(tz); n = cfg["night"]
        night = bool(n["enabled"] and in_night(now, n["off_at"], n["on_at"]))
        w = None
        if cfg["weather"]["enabled"]:
            if time.time() - weather["ts"] > 900:
                try: weather["data"] = fetch_weather()
                except Exception as e: logging.warning("weather: %s", e)
                weather["ts"] = time.time()
            w = weather["data"]
        return jsonify(now=now.isoformat(), timezone=cfg["timezone"], night=night, weather=w, mock=cfg["mock"])
    @app.get("/healthz")
    def health(): return "ok"
    return app

def main():
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    create_app(cfg).run(host=cfg["server"]["host"], port=cfg["server"]["port"], threaded=True)

if __name__ == "__main__":
    main()
