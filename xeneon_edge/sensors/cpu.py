"""CPU load, clock, temp, name — pure /proc + /sys."""
from __future__ import annotations
from pathlib import Path
import time

_PROC_STAT = Path("/proc/stat")
_PROC_CPUINFO = Path("/proc/cpuinfo")
_HWMON = Path("/sys/class/hwmon")


def _read_proc_stat_aggregate() -> tuple[int, int]:
    line = _PROC_STAT.read_text().splitlines()[0]
    # cpu user nice system idle iowait irq softirq steal guest guest_nice
    parts = [int(x) for x in line.split()[1:]]
    idle = parts[3] + parts[4]  # idle + iowait
    total = sum(parts)
    return total, idle


class CpuLoadTracker:
    def __init__(self) -> None:
        self._last = _read_proc_stat_aggregate()
        self._last_t = time.monotonic()

    def sample(self) -> float | None:
        try:
            total, idle = _read_proc_stat_aggregate()
        except OSError:
            return None
        d_total = total - self._last[0]
        d_idle = idle - self._last[1]
        self._last = (total, idle)
        if d_total <= 0:
            return None
        return max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))


def cpu_clock_mhz() -> float | None:
    try:
        text = _PROC_CPUINFO.read_text()
    except OSError:
        return None
    vals = []
    for line in text.splitlines():
        if line.startswith("cpu MHz"):
            try:
                vals.append(float(line.split(":", 1)[1]))
            except ValueError:
                pass
    if not vals:
        return None
    return sum(vals) / len(vals)


def cpu_name() -> str:
    try:
        text = _PROC_CPUINFO.read_text()
    except OSError:
        return "CPU"
    for line in text.splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "CPU"


def _hwmon_iter():
    if not _HWMON.exists():
        return
    for entry in sorted(_HWMON.iterdir()):
        name_file = entry / "name"
        if not name_file.exists():
            continue
        try:
            yield entry, name_file.read_text().strip()
        except OSError:
            continue


_TEMP_DRIVERS = ("k10temp", "zenpower", "coretemp", "k8temp")


def cpu_temp_c() -> float | None:
    """Pick the first matching CPU hwmon driver and return Tctl/package temp."""
    for path, name in _hwmon_iter():
        if name not in _TEMP_DRIVERS:
            continue
        # prefer Tctl/Tdie/Package label, else temp1_input
        label_match = None
        for label_file in sorted(path.glob("temp*_label")):
            try:
                lbl = label_file.read_text().strip()
            except OSError:
                continue
            input_file = path / label_file.name.replace("_label", "_input")
            if not input_file.exists():
                continue
            if lbl in ("Tctl", "Tdie", "Package id 0"):
                label_match = input_file
                break
            if label_match is None:
                label_match = input_file
        if label_match is None:
            label_match = path / "temp1_input"
            if not label_match.exists():
                continue
        try:
            return int(label_match.read_text().strip()) / 1000.0
        except (OSError, ValueError):
            continue
    return None


def cpu_power_w() -> float | None:
    """Best-effort CPU package power via RAPL energy counter (W)."""
    rapl = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
    if not rapl.exists():
        rapl = Path("/sys/class/powercap/amd_energy/energy0_input")
    if not rapl.exists():
        return None
    try:
        e1 = int(rapl.read_text().strip())
    except (OSError, ValueError):
        return None
    t1 = time.monotonic()
    time.sleep(0.05)
    try:
        e2 = int(rapl.read_text().strip())
    except (OSError, ValueError):
        return None
    t2 = time.monotonic()
    dt = t2 - t1
    if dt <= 0:
        return None
    return max(0.0, (e2 - e1) / 1_000_000 / dt)
