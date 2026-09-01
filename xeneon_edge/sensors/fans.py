"""Fan RPMs from /sys/class/hwmon."""
from __future__ import annotations
from pathlib import Path

_HWMON = Path("/sys/class/hwmon")


def fan_metrics() -> list[dict]:
    out: list[dict] = []
    if not _HWMON.exists():
        return out
    for entry in sorted(_HWMON.iterdir()):
        try:
            chip = (entry / "name").read_text().strip()
        except OSError:
            chip = entry.name
        for fan_input in sorted(entry.glob("fan*_input")):
            stem = fan_input.name.replace("_input", "")
            label_file = entry / f"{stem}_label"
            try:
                label = label_file.read_text().strip()
            except OSError:
                label = stem
            try:
                rpm = int(fan_input.read_text().strip())
            except (OSError, ValueError):
                continue
            out.append({"label": f"{chip}/{label}", "rpm": rpm})
    return out
