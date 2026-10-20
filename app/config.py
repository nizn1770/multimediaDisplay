import copy, os, re, yaml
DEFAULTS = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.example.yaml")))
def _merge(a, b):
    for k, v in (b or {}).items():
        a[k] = _merge(a.get(k, {}), v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a
def _looks_octal(path, val):
    """True if the raw YAML wrote the pin with a leading 0 (YAML 1.1 octal)."""
    try:
        m = re.search(r"^\s*pin:\s*(0[0-7]+)\s*(#.*)?$", open(path).read(), re.M)
        return bool(m) and int(m.group(1), 8) == val
    except Exception:
        return False
def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("PITV_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config.local.yaml"))
    if os.path.exists(path):
        user = yaml.safe_load(open(path)) or {}
        if not isinstance(user, dict):
            raise ValueError(f"{path}: top level must be a mapping")
        ucal = user.get("calendar") or {}
        if isinstance(ucal, dict) and "calendar_ids" in ucal and "calendars" not in ucal:
            cfg["calendar"].pop("calendars", None)   # legacy key wins over the example placeholder
        _merge(cfg, user)
    pin = (cfg.get("settings") or {}).get("pin")
    if pin is not None and not isinstance(pin, str):
        # unquoted 0123 is YAML-octal (83) / 1234 is int: keep digits as typed where we can
        cfg["settings"]["pin"] = oct(pin)[2:].zfill(4) if isinstance(pin, int) and pin and _looks_octal(path, pin) else str(pin)
    for k in ("on_at", "off_at"):  # unquoted 06:30 in YAML 1.1 parses as base-60 int (390)
        v = cfg["night"].get(k)
        if isinstance(v, int): cfg["night"][k] = f"{v // 60:02d}:{v % 60:02d}"
    if os.environ.get("PITV_MOCK"):
        cfg["mock"] = os.environ["PITV_MOCK"] not in ("0", "false")
    return cfg

PALETTE = ["#4a90e2", "#e94e77", "#50c878", "#f5a623", "#9b59b6", "#1abc9c"]
def calendars(cfg):
    """Normalise calendar config -> [{id,name,color}]. Accepts legacy calendar_ids list."""
    c = cfg["calendar"]
    items = c.get("calendars") or [{"id": i} for i in (c.get("calendar_ids") or [])]
    return [{"id": x["id"], "name": x.get("name", x["id"]), "color": x.get("color", PALETTE[i % len(PALETTE)])}
            for i, x in enumerate(items)]

import re, tempfile
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
def local_path():
    return os.environ.get("PITV_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config.local.yaml"))
def validate_hours(on_at, off_at):
    for v in (on_at, off_at):
        if not isinstance(v, str) or not HHMM.match(v):
            raise ValueError(f"time must be HH:MM (24h), got {v!r}")
    if on_at == off_at:
        raise ValueError("on and off times must differ")
class _Dumper(yaml.SafeDumper): pass
def _str(d, v):  # always quote strings like 06:30 (YAML 1.1 would read them as base-60 ints)
    style = '"' if (HHMM.match(v) or ":" in v) else None
    return d.represent_scalar("tag:yaml.org,2002:str", v, style=style)
_Dumper.add_representer(str, _str)
def save_local(updates, path=None):
    """Deep-merge updates into config.local.yaml atomically (preserves other keys)."""
    path = path or local_path()
    cur = (yaml.safe_load(open(path)) or {}) if os.path.exists(path) else {}
    _merge(cur, updates)
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cfg-", suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(cur, f, Dumper=_Dumper, sort_keys=False, allow_unicode=True)
    if os.path.exists(path):
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    os.replace(tmp, path)
    return cur
