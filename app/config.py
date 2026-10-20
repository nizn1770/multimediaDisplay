import copy, os, yaml
DEFAULTS = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.example.yaml")))
def _merge(a, b):
    for k, v in (b or {}).items():
        a[k] = _merge(a.get(k, {}), v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a
def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("PITV_CONFIG", "config.yaml")
    if os.path.exists(path):
        _merge(cfg, yaml.safe_load(open(path)) or {})
    if os.environ.get("PITV_MOCK"):
        cfg["mock"] = os.environ["PITV_MOCK"] not in ("0", "false")
    return cfg
