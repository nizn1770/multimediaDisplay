import copy, os, yaml
DEFAULTS = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.example.yaml")))
def _merge(a, b):
    for k, v in (b or {}).items():
        a[k] = _merge(a.get(k, {}), v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a
def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("PITV_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config.local.yaml"))
    if os.path.exists(path):
        _merge(cfg, yaml.safe_load(open(path)) or {})
    if os.environ.get("PITV_MOCK"):
        cfg["mock"] = os.environ["PITV_MOCK"] not in ("0", "false")
    return cfg

PALETTE = ["#4a90e2", "#e94e77", "#50c878", "#f5a623", "#9b59b6", "#1abc9c"]
def calendars(cfg):
    """Normalise calendar config -> [{id,name,color}]. Accepts legacy calendar_ids list."""
    c = cfg["calendar"]
    items = c.get("calendars") or [{"id": i} for i in c.get("calendar_ids", [])]
    return [{"id": x["id"], "name": x.get("name", x["id"]), "color": x.get("color", PALETTE[i % len(PALETTE)])}
            for i, x in enumerate(items)]
