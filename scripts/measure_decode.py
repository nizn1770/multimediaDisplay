#!/usr/bin/env python3
"""Measure peak RSS of downscale() for one image in a fresh process.
Usage: measure_decode.py IMAGE  -> prints JSON {base_mb, peak_mb, delta_mb, result}"""
import json, os, resource, sys, tempfile

def hwm_kb():
    """Peak RSS of *this* process image (VmHWM). ru_maxrss would include the pre-exec parent."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmHWM:"): return int(line.split()[1])
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services import downscale, OversizedImage  # noqa: E402  (imports PIL + pillow-heif first)
from PIL import Image  # noqa: E402
base = hwm_kb()
out = tempfile.mktemp(suffix=".jpg")
try:
    downscale(sys.argv[1], out); res = "x".join(map(str, Image.open(out).size))
except OversizedImage as e:
    res = f"oversized: {e}"
peak = hwm_kb()
print(json.dumps({"base_mb": base // 1024, "peak_mb": peak // 1024, "delta_mb": (peak - base) // 1024, "result": res}))
