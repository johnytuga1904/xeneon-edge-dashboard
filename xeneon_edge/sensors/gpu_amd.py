"""AMD GPU sensors via /sys/class/drm/cardX/device/."""
from __future__ import annotations
from pathlib import Path

_DRM = Path("/sys/class/drm")
_AMD_VENDOR = "0x1002"


def _amd_cards() -> list[Path]:
    if not _DRM.exists():
        return []
    out: list[Path] = []
    for entry in sorted(_DRM.iterdir()):
        if not entry.name.startswith("card") or "-" in entry.name:
            continue
        device = entry / "device"
        vendor_file = device / "vendor"
        if not vendor_file.exists():
            continue
        try:
            if vendor_file.read_text().strip() != _AMD_VENDOR:
                continue
        except OSError:
            continue
        out.append(device)
    return out


def _read_int(p: Path) -> int | None:
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None


def _name_for(device: Path) -> str:
    # /sys/class/drm/card2/device/uevent contains DRIVER=amdgpu but not name
    # Try product info via /sys/bus/pci/devices/<slot>/.../product_name (rare).
    # Fallback: parse PCI_ID from modalias and look up via hwids if available, otherwise generic.
    try:
        modalias = (device / "modalias").read_text().strip()
    except OSError:
        return "AMD GPU"
    return f"AMD GPU ({modalias.split(':d')[1][:8] if ':d' in modalias else 'Radeon'})"


def gpu_amd_metrics() -> list[dict]:
    out: list[dict] = []
    for device in _amd_cards():
        load_pct = _read_int(device / "gpu_busy_percent")
        vram_used = _read_int(device / "mem_info_vram_used")
        vram_total = _read_int(device / "mem_info_vram_total")

        temp_c = power_w = core_mhz = mem_mhz = fan_rpm = None
        hwmon_dir = device / "hwmon"
        if hwmon_dir.exists():
            for h in sorted(hwmon_dir.iterdir()):
                t = _read_int(h / "temp1_input")
                if t is not None:
                    temp_c = t / 1000.0
                p = _read_int(h / "power1_average")
                if p is not None:
                    power_w = p / 1_000_000.0
                # freq labels: sclk = core, mclk = memory (in Hz)
                for label_file in sorted(h.glob("freq*_label")):
                    try:
                        lbl = label_file.read_text().strip()
                    except OSError:
                        continue
                    val = _read_int(h / label_file.name.replace("_label", "_input"))
                    if val is None:
                        continue
                    mhz = val / 1_000_000.0
                    if lbl == "sclk":
                        core_mhz = mhz
                    elif lbl == "mclk":
                        mem_mhz = mhz
                fan = _read_int(h / "fan1_input")
                if fan is not None:
                    fan_rpm = fan
                break

        out.append({
            "name": _name_for(device),
            "vendor": "amd",
            "load_pct": float(load_pct) if load_pct is not None else None,
            "vram_used_gb": vram_used / (1024**3) if vram_used else None,
            "vram_total_gb": vram_total / (1024**3) if vram_total else None,
            "temp_c": temp_c,
            "power_w": power_w,
            "core_mhz": core_mhz,
            "mem_mhz": mem_mhz,
            "fan_rpm": fan_rpm,
        })
    return out
