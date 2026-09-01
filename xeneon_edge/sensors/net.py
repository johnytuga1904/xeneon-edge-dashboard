"""Network throughput via /proc/net/dev."""
from __future__ import annotations
from pathlib import Path
import time

_NETDEV = Path("/proc/net/dev")


def _read_totals() -> tuple[int, int]:
    rx_total = 0
    tx_total = 0
    try:
        text = _NETDEV.read_text()
    except OSError:
        return 0, 0
    for line in text.splitlines()[2:]:
        iface, _, rest = line.partition(":")
        iface = iface.strip()
        if iface.startswith(("lo", "docker", "veth", "br-", "virbr", "tun", "tap")):
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            rx_total += int(parts[0])
            tx_total += int(parts[8])
        except ValueError:
            continue
    return rx_total, tx_total


class NetTracker:
    def __init__(self) -> None:
        self._last = _read_totals()
        self._last_t = time.monotonic()

    def sample(self) -> tuple[float, float]:
        rx, tx = _read_totals()
        t = time.monotonic()
        dt = max(1e-3, t - self._last_t)
        d_rx = max(0, rx - self._last[0])
        d_tx = max(0, tx - self._last[1])
        self._last = (rx, tx)
        self._last_t = t
        # bytes/sec → Mbps
        return d_rx / dt * 8 / 1_000_000, d_tx / dt * 8 / 1_000_000
