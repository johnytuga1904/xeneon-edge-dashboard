"""NVIDIA GPU sensors: NVML (pynvml) wenn vorhanden, sonst nvidia-smi.

nvidia-smi ist ein Prozessstart pro Tick — gemessen 28 ms, bei 1 Hz ein
spuerbarer Teil der Dashboard-CPU. NVML fragt dieselben Werte in-process
ab, gemessen 0,1 ms. Das Paket heisst nvidia-ml-py (Arch:
python-nvidia-ml-py, Debian: python3-pynvml); fehlt es, bleibt alles wie
vorher. Welcher Weg laeuft, meldet ``source_name()`` fuer die Statuspille.
"""
from __future__ import annotations
import shutil
import subprocess

try:
    import pynvml  # type: ignore
except ImportError:  # optional
    pynvml = None  # type: ignore

_QUERY = (
    "name,temperature.gpu,utilization.gpu,memory.used,memory.total,"
    "clocks.gr,clocks.mem,power.draw,fan.speed"
)

_warned = False
# None = noch nicht versucht, True = laeuft, False = NVML unbrauchbar (kein
# Treiber, alte Bibliothek) — dann dauerhaft nvidia-smi.
_nvml_ok: bool | None = None
_source: str | None = None


def source_name() -> str | None:
    """"nvml" oder "smi" — was zuletzt Werte geliefert hat, sonst None."""
    return _source


# ----- NVML -----

def _nvml_init() -> bool:
    global _nvml_ok
    if _nvml_ok is not None:
        return _nvml_ok
    if pynvml is None:
        _nvml_ok = False
        return False
    try:
        pynvml.nvmlInit()
        _nvml_ok = True
    except Exception as e:  # NVMLError oder fehlende libnvidia-ml.so
        print(f"[xeneon-edge] NVML unusable ({e}) — using nvidia-smi")
        _nvml_ok = False
    return _nvml_ok


def _nv(fn, *args):
    """Einen NVML-Aufruf machen; ein fehlender Sensor ist None, kein Fehler."""
    try:
        return fn(*args)
    except Exception:
        return None


def _nvml_metrics() -> list[dict] | None:
    """None heisst: NVML ist kaputt gegangen, der Aufrufer nimmt nvidia-smi."""
    global _nvml_ok
    try:
        count = pynvml.nvmlDeviceGetCount()
    except Exception as e:
        print(f"[xeneon-edge] NVML failed ({e}) — using nvidia-smi from now on")
        _nvml_ok = False
        return None

    out: list[dict] = []
    for i in range(count):
        h = _nv(pynvml.nvmlDeviceGetHandleByIndex, i)
        if h is None:
            continue
        name = _nv(pynvml.nvmlDeviceGetName, h)
        if isinstance(name, bytes):
            name = name.decode(errors="replace")
        util = _nv(pynvml.nvmlDeviceGetUtilizationRates, h)
        mem = _nv(pynvml.nvmlDeviceGetMemoryInfo, h)
        temp = _nv(pynvml.nvmlDeviceGetTemperature, h, pynvml.NVML_TEMPERATURE_GPU)
        clk_gr = _nv(pynvml.nvmlDeviceGetClockInfo, h, pynvml.NVML_CLOCK_GRAPHICS)
        clk_mem = _nv(pynvml.nvmlDeviceGetClockInfo, h, pynvml.NVML_CLOCK_MEM)
        power = _nv(pynvml.nvmlDeviceGetPowerUsage, h)  # mW
        fan = _nv(pynvml.nvmlDeviceGetFanSpeed, h)      # %, passiv gekuehlt: Fehler
        out.append({
            "name": name or "NVIDIA GPU",
            "vendor": "nvidia",
            "load_pct": float(util.gpu) if util is not None else None,
            "vram_used_gb": mem.used / 1024**3 if mem is not None else None,
            "vram_total_gb": mem.total / 1024**3 if mem is not None else None,
            "temp_c": float(temp) if temp is not None else None,
            "power_w": power / 1000.0 if power is not None else None,
            "core_mhz": float(clk_gr) if clk_gr is not None else None,
            "mem_mhz": float(clk_mem) if clk_mem is not None else None,
            "fan_rpm": None,  # NVML kennt nur Prozent
            "fan_pct": float(fan) if fan is not None else None,
        })
    return out


# ----- nvidia-smi -----

def _f(s: str) -> float | None:
    s = s.strip()
    if not s or s.lower().startswith("[n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _smi_metrics() -> list[dict]:
    global _warned
    smi = shutil.which("nvidia-smi")
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


def gpu_nvidia_metrics() -> list[dict]:
    global _source
    if _nvml_init():
        result = _nvml_metrics()
        if result is not None:
            _source = "nvml" if result else None
            return result
    result = _smi_metrics()
    _source = "smi" if result else None
    return result
