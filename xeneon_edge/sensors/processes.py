"""Top processes via psutil."""
from __future__ import annotations

try:
    import psutil  # type: ignore
except ImportError:  # graceful — show empty list
    psutil = None  # type: ignore


def top_processes(limit: int = 8) -> list[dict]:
    if psutil is None:
        return []
    procs: list[dict] = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            info = p.info
            mem = info["memory_info"]
            if mem is None:
                continue
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "?",
                "ram_mb": mem.rss / (1024 * 1024),
                "cpu_pct": info["cpu_percent"] or 0.0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x["ram_mb"], reverse=True)
    return procs[:limit]


def kill_pid(pid: int) -> bool:
    if psutil is None:
        return False
    try:
        psutil.Process(pid).terminate()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
