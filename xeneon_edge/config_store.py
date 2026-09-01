"""Persistence: settings.json + apps.json (user-config preferred over packaged)."""
from __future__ import annotations
import json
from pathlib import Path

from .paths import APPS_FILE, USER_APPS_FILE, USER_SETTINGS_FILE, USER_CONFIG_DIR

_DEFAULT_SETTINGS = {
    "auto_start": False,
    "hold_to_confirm": True,
    # Where to open the dashboard. Empty/None → auto-detect a 2560x720 monitor
    # (Corsair Xeneon Edge); fallback to default display.
    # Set to a connector name like "DP-5" to pin manually.
    "target_monitor": "",
    "fullscreen_on_target": True,
    # Deck-Eintraege ueber `systemd-run --user` in eigene transiente Units
    # starten statt als Kindprozess des Dashboards. Siehe launcher.py.
    "isolate_launches": True,
    # Leer = eingebettetes TradingView-Widget (kein Login, kein Account).
    # Eine URL wie "https://www.tradingview.com/chart/AbCdEf12/" laedt
    # stattdessen die echte Chart-Seite mit der gespeicherten Session, also mit
    # deinem Layout. Login einmalig ueber scripts/tradingview-login.py.
    "chart_url": "",
    # Wie viele der DECK_SLOTS Plaetze an Apps gehen; der Rest geht an Macros.
    # 0 = alles Macros, DECK_SLOTS = alles Apps.
    "deck_app_slots": 9,
}

AUTOSTART_DESKTOP = Path.home() / ".config" / "autostart" / "xeneon-edge.desktop"

# Deck-Geometrie: 3 Spalten x 6 Zeilen. Die Buttonhoehe ist auf die 660px
# Inhaltsflaeche des Xeneon Edge abgestimmt — mehr Zeilen machen die Buttons
# kleiner als per Touch sinnvoll treffbar.
DECK_COLS = 3
DECK_ROWS = 6
DECK_SLOTS = DECK_COLS * DECK_ROWS


def deck_split(settings: dict) -> tuple[int, int]:
    """(Slots fuer Apps, Slots fuer Macros) — zusammen immer DECK_SLOTS."""
    try:
        app_slots = int(settings.get("deck_app_slots", 9))
    except (TypeError, ValueError):
        app_slots = 9
    app_slots = max(0, min(DECK_SLOTS, app_slots))
    return app_slots, DECK_SLOTS - app_slots


def load_settings() -> dict:
    if USER_SETTINGS_FILE.exists():
        try:
            return {**_DEFAULT_SETTINGS, **json.loads(USER_SETTINGS_FILE.read_text())}
        except (OSError, json.JSONDecodeError):
            pass
    return dict(_DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def load_apps() -> dict:
    """Returns {'apps': [...], 'macros': [...]}."""
    candidates = [USER_APPS_FILE, APPS_FILE]
    for f in candidates:
        if f.exists():
            try:
                return json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
    return {"apps": [], "macros": []}


def save_apps(data: dict) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_APPS_FILE.write_text(json.dumps(data, indent=2))


def _desktop_exec_quote(path: Path) -> str:
    """Quote a path for a Desktop Entry ``Exec=`` value.

    The spec splits Exec on unquoted whitespace, so any path containing a
    space (e.g. ".../Monitor dashboard/...") must be double-quoted, with
    ``"``, ``$``, `````` and ``\\`` backslash-escaped inside the quotes.
    """
    s = str(path)
    esc = (s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("`", "\\`")
            .replace("$", "\\$"))
    return f'"{esc}"'


def install_autostart(run_path: Path) -> None:
    AUTOSTART_DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_DESKTOP.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Xeneon Edge Dashboard\n"
        f"Exec={_desktop_exec_quote(run_path)}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n"
    )


def uninstall_autostart() -> None:
    if AUTOSTART_DESKTOP.exists():
        try:
            AUTOSTART_DESKTOP.unlink()
        except OSError:
            pass
