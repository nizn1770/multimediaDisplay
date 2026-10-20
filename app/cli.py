import json, os, re, subprocess, sys, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml
from app.config import load_config, save_local, validate_hours, local_path

SENSITIVE = ("folder_id", "id", "pin", "service_account_file", "oauth_client_file", "oauth_token_file")
def mask(o, key=None):
    if isinstance(o, dict): return {k: mask(v, k) for k, v in o.items()}
    if isinstance(o, list): return [mask(v, key) for v in o]
    if key in SENSITIVE and isinstance(o, str) and o and not o.startswith("YOUR_") and "/" not in o:
        return o[:3] + "…(hidden)"
    return o
def api(path, body=None):
    port = load_config(local_path())["server"]["port"]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=5))
USAGE = """usage: pitv set-hours ON_AT OFF_AT   e.g. pitv set-hours 06:30 23:00
       pitv night on|off                 enable/disable night screen-off
       pitv show-config [--reveal]       effective config (IDs masked unless --reveal)
       pitv screen on|off                switch the TV now
       pitv control next|prev|pause|resume|photos|week|month
       pitv status"""
def main(a):
    if not a or a[0] in ("-h", "--help", "help"): print(USAGE); return 0
    cmd = a[0]
    if cmd == "set-hours" and len(a) == 3:
        try: validate_hours(a[1], a[2])
        except ValueError as e: print("error:", e, file=sys.stderr); return 2
        save_local({"night": {"on_at": a[1], "off_at": a[2]}})
        print(f"screen on {a[1]}, off {a[2]} saved to {os.path.relpath(local_path())} (applies within 30 s, no restart)"); return 0
    if cmd == "night" and len(a) == 2 and a[1] in ("on", "off"):
        save_local({"night": {"enabled": a[1] == "on"}}); print("night screen-off", a[1]); return 0
    if cmd == "show-config":
        c = load_config(local_path()); print(yaml.safe_dump(c if "--reveal" in a else mask(c), sort_keys=False, allow_unicode=True)); return 0
    if cmd == "screen" and len(a) == 2 and a[1] in ("on", "off"):
        return subprocess.call([os.path.join(os.path.dirname(__file__), "..", "scripts", "screen.sh"), a[1]])
    if cmd == "control" and len(a) == 2:
        try: print(api("/api/control", {"action": a[1], "pin": os.environ.get("PITV_PIN", "")})); return 0
        except Exception as e: print("error:", e, file=sys.stderr); return 1
    if cmd == "status":
        try: print(json.dumps(api("/api/status"), indent=2)); return 0
        except Exception as e: print("server not reachable:", e, file=sys.stderr); return 1
    print(USAGE, file=sys.stderr); return 2
if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
