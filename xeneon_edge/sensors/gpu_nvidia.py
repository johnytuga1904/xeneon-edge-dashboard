"""NVIDIA GPU sensors via nvidia-smi.

Falls nvidia-smi nicht installiert ist, einmalig warnen und leere Liste liefern.
"""
from __future__ import annotations
import shutil
import subprocess

_QUERY = (
    "name,temperature.gpu,utilization.gpu,memory.used,memory.total,"
    "clocks.gr,clocks.mem,power.draw,fan.speed"
)

_warned = False


def _nvidia_smi_path() -> str | None:
    return shutil.which("nvidia-smi")


def _f(s: str) -> float | None:
    s = s.strip()
    if not s or s.lower().startswith("[n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def gpu_nvidia_metrics() -> list[dict]:
    global _warned
    smi = _nvidia_smi_path()
    if smi is None:
        if not _warned:
            print("[xeneon-edge] nvidia-smi not found; NVIDIA GPU panel disabled. "
                  "Install nvidia drivers/utils to enable.")
            _warned = True
        return []

    try:
        proc = subprocess.run(
            [smi, f"--query-gpu={_QUERY}", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=2,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []

    out: list[dict] = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        name, temp, util, mem_used, mem_total, clk_gr, clk_mem, power, fan = parts
        out.append({
            "name": name,
            "vendor": "nvidia",
            "load_pct": _f(util),
            "vram_used_gb": (_f(mem_used) or 0) / 1024 if _f(mem_used) is not None else None,
            "vram_total_gb": (_f(mem_total) or 0) / 1024 if _f(mem_total) is not None else None,
            "temp_c": _f(temp),
            "power_w": _f(power),
            "core_mhz": _f(clk_gr),
            "mem_mhz": _f(clk_mem),
            "fan_rpm": None,  # nvidia-smi gives % not RPM
            "fan_pct": _f(fan),
        })
    return out
