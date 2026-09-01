"""Pick the Corsair Xeneon Edge monitor (2560x720) or any user-configured one."""
from __future__ import annotations
import gi
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402


XENEON_EDGE_W = 2560
XENEON_EDGE_H = 720


def _all_monitors(display: Gdk.Display) -> list[Gdk.Monitor]:
    monitors_list = display.get_monitors()
    out: list[Gdk.Monitor] = []
    for i in range(monitors_list.get_n_items()):
        m = monitors_list.get_item(i)
        if m is not None:
            out.append(m)
    return out


def _connector_name(monitor: Gdk.Monitor) -> str:
    # GTK4: Gdk.Monitor.get_connector() returns the DRM connector name (e.g. "DP-5")
    try:
        return monitor.get_connector() or ""
    except Exception:
        return ""


def describe(monitor: Gdk.Monitor) -> str:
    g = monitor.get_geometry()
    return f"{_connector_name(monitor)} ({g.width}x{g.height} @ {g.x},{g.y})"


def find_target_monitor(display: Gdk.Display, preferred_connector: str = "") -> Gdk.Monitor | None:
    monitors = _all_monitors(display)
    if not monitors:
        return None

    # 1) explicit override
    if preferred_connector:
        for m in monitors:
            if _connector_name(m) == preferred_connector:
                return m

    # 2) auto-detect Xeneon Edge by 2560x720 geometry
    for m in monitors:
        g = m.get_geometry()
        if g.width == XENEON_EDGE_W and g.height == XENEON_EDGE_H:
            return m

    # 3) fall back to None (caller decides)
    return None


def list_monitors_for_settings(display: Gdk.Display) -> list[tuple[str, str]]:
    """Returns [(connector_name, label)] for the settings dropdown."""
    out: list[tuple[str, str]] = []
    for m in _all_monitors(display):
        out.append((_connector_name(m), describe(m)))
    return out
