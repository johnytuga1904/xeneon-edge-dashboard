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


def find_login_monitor(display: Gdk.Display, dashboard_connector: str = "") -> Gdk.Monitor | None:
    """Der groesste Monitor, der *nicht* der Dashboard-Streifen ist.

    Fuer Fenster, die Tastatur brauchen — bislang nur das TradingView-Login.
    Am 2560x720-Streifen haengt keine, und das Dashboard liegt dort im Vollbild
    davor: ein Fenster, das da aufgeht, ist weder sichtbar noch bedienbar.
    Hyprland legt neue Fenster aber auf den fokussierten Workspace, und der ist
    genau dann der Streifen, wenn das Login per Touch aus dem Dashboard heraus
    gestartet wurde.

    Faellt auf None zurueck, wenn nur der Streifen angeschlossen ist — dann
    bleibt es beim Standardverhalten des Compositors.
    """
    dashboard = dashboard_connector or ""
    others = [m for m in _all_monitors(display) if _connector_name(m) != dashboard]
    if not others:
        return None
    return max(others, key=lambda m: m.get_geometry().width * m.get_geometry().height)


def list_monitors_for_settings(display: Gdk.Display) -> list[tuple[str, str]]:
    """Returns [(connector_name, label)] for the settings dropdown."""
    out: list[tuple[str, str]] = []
    for m in _all_monitors(display):
        out.append((_connector_name(m), describe(m)))
    return out
