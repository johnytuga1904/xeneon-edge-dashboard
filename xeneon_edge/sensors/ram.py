"""RAM via /proc/meminfo."""
from __future__ import annotations
from pathlib import Path

_MEMINFO = Path("/proc/meminfo")


def ram_metrics() -> dict | None:
    try:
        text = _MEMINFO.read_text()
    except OSError:
        return None
    fields: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        rest = rest.strip()
        if rest.endswith("kB"):
            try:
                fields[key] = int(rest[:-2].strip())  # kB
            except ValueError:
                pass
    total = fields.get("MemTotal")
    available = fields.get("MemAvailable")
    if total is None or available is None:
        return None
    used = total - available
    used_gb = used / 1024 / 1024
    total_gb = total / 1024 / 1024
    load = used / total * 100.0 if total else 0.0
    return {"used_gb": used_gb, "total_gb": total_gb, "load_pct": load}
