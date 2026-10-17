"""Editor: Nutzlast fuer die Seite, Auswertung dessen was zurueckkommt.

Der Editor ist seit Schritt 4 der einzige Ort fuer Einstellungen: Layout
(Spalten und Topbar), Einstellungen jedes Moduls, das Launch-Deck und die
globalen Settings. Die Seite liegt in assets/ und wird von
scripts/layout-editor.py in einem WebKit-Fenster auf dem *Haupt*monitor
geoeffnet — am Streifen haengt keine Tastatur.

Hier steht bewusst nur, was ohne GTK und ohne WebKit testbar ist: die
Nutzlast zusammenbauen und eine Nachricht aus der Seite verarbeiten. Alles,
was ein Fenster braucht (Login-Fenster starten, Datei-Picker), steht im
Skript.
"""
from __future__ import annotations
import json
from typing import Any

from .. import config_store, layout_store, modules, theme
from ..paths import EDITOR_ASSETS_DIR, ROOT

# Wenn kein Streifen gefunden wird: die Geometrie, fuer die das Dashboard
# entworfen ist. Der Editor muss *irgendeine* Bezugsbreite haben, sonst kann er
# keine Proportionen zeichnen.
FALLBACK_STAGE = {"width": 2560, "height": 720, "connector": ""}

# Was die Seite an settings.json aendern darf. Alles andere (chart_url und
# openmarket_url, die das Login-Fenster schreibt) bleibt, wie es ist.
SETTINGS_KEYS = (
    "theme", "target_monitor", "launch_monitor", "fullscreen_on_target",
    "auto_start", "hold_to_confirm", "isolate_launches", "deck_app_slots",
    "web_memory_limit_mb",
)

# Formular fuer die globalen Einstellungen — dieselbe Feldbeschreibung wie bei
# den Modulen, damit die Seite nur einen Formular-Renderer braucht. Optionen
# fuer theme und target_monitor haengt payload() zur Laufzeit an.
SETTINGS_SCHEMA = (
    modules.Field("theme", "Colour theme", "select", default=theme.DEFAULT),
    modules.Field("target_monitor", "Target monitor", "select", default="",
                  help="Empty = look for a 2560x720 monitor automatically"),
    modules.Field("fullscreen_on_target", "Fullscreen on the target monitor", "bool", default=True),
    modules.Field("launch_monitor", "Monitor for launched windows", "select", default="",
                  help="Where everything the dashboard opens goes: deck entries, "
                       "this editor, the TradingView login. Empty = the compositor "
                       "decides, in practice the most recently focused monitor — "
                       "which may be the strip itself, where no keyboard is attached."),
    modules.Field("auto_start", "Start with the session", "bool", default=False,
                  help="Writes ~/.config/autostart/xeneon-edge.desktop"),
    modules.Field("hold_to_confirm", "Hold to confirm dangerous macros", "bool", default=True,
                  help="Hold for one second for shutdown, reboot etc."),
    modules.Field("isolate_launches", "Deck entries in their own systemd unit", "bool", default=True,
                  help="Own cgroup: an LLM server cannot slow the dashboard down"),
    modules.Field("web_memory_limit_mb", "Web panel memory cap (MB)", "int", default=1536,
                  min=0, max=8192,
                  help="RSS of the WebKit process; at the limit the page is reloaded. 0 = off"),
)


def catalogue() -> list[dict[str, Any]]:
    """Verfuegbare Spalten-Module fuer das Hinzufuegen-Menue."""
    return [spec.to_dict() for spec in modules.all_specs()]


def topbar_catalogue() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in modules.all_topbar_specs()]


def payload(stage: dict | None = None, palette: theme.Palette | None = None,
            monitors: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Alles, was die Seite zum Zeichnen braucht."""
    palette = palette or theme.load(None)
    settings = config_store.load_settings()
    schema = []
    for f in SETTINGS_SCHEMA:
        d = f.to_dict()
        if f.key == "theme":
            d["options"] = [list(t) for t in theme.available()]
        elif f.key == "target_monitor":
            d["options"] = [["", "automatic (look for 2560x720)"]] + \
                           [[c, label] for c, label in (monitors or [])]
        elif f.key == "launch_monitor":
            d["options"] = [["", "compositor decides"]] + \
                           [[c, label] for c, label in (monitors or [])]
        schema.append(d)
    return {
        "layout": layout_store.load(),
        "settings": {k: settings.get(k) for k in SETTINGS_KEYS},
        "settings_schema": schema,
        "apps": config_store.load_apps(),
        "deck": {"cols": config_store.DECK_COLS, "rows": config_store.DECK_ROWS,
                 "slots": config_store.DECK_SLOTS},
        "catalogue": catalogue(),
        "topbar_catalogue": topbar_catalogue(),
        "topbar_slots": list(layout_store.TOPBAR_SLOTS),
        "stage": dict(stage or FALLBACK_STAGE),
        "palette": {key: getattr(palette, key) for key in theme.COLOR_KEYS},
        "flex": layout_store.FLEX,
    }


def build_page(payload_data: dict[str, Any]) -> str:
    """HTML, CSS, JS und Nutzlast zu einer Seite verschmelzen.

    Eine einzige Seite statt drei Dateien per file://: WebKit behandelt lokale
    Unterressourcen je nach Version und Sandbox unterschiedlich streng, und der
    Editor ist klein genug, dass Einbetten nichts kostet.
    """
    html = (EDITOR_ASSETS_DIR / "editor.html").read_text()
    css = (EDITOR_ASSETS_DIR / "editor.css").read_text()
    js = (EDITOR_ASSETS_DIR / "editor.js").read_text()

    # </script> im JSON wuerde das umgebende <script> vorzeitig schliessen.
    data = json.dumps(payload_data, ensure_ascii=False).replace("</", "<\\/")

    return (html
            .replace("/*CSS*/", css)
            .replace("/*PAYLOAD*/", f"window.__PAYLOAD__ = {data};")
            .replace("/*JS*/", js))


class SaveResult:
    def __init__(self, ok: bool, message: str) -> None:
        self.ok = ok
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover
        return f"SaveResult(ok={self.ok}, message={self.message!r})"


def _save_settings(incoming: Any) -> None:
    """Nur bekannte Schluessel uebernehmen; Autostart hat einen Nebeneffekt."""
    if not isinstance(incoming, dict):
        return
    current = config_store.load_settings()
    for key in SETTINGS_KEYS:
        if key in incoming:
            current[key] = incoming[key]
    config_store.save_settings(current)
    if current.get("auto_start"):
        config_store.install_autostart(ROOT / "run.sh")
    else:
        config_store.uninstall_autostart()


def _save_apps(incoming: Any) -> None:
    if not isinstance(incoming, dict):
        return
    data = {"apps": [e for e in incoming.get("apps", []) if isinstance(e, dict)],
            "macros": [e for e in incoming.get("macros", []) if isinstance(e, dict)]}
    config_store.save_apps(data)


def handle_message(raw: str) -> SaveResult:
    """Eine Speichern-Nachricht aus der Seite verarbeiten.

    Die Seite schickt JSON mit ``layout`` und optional ``settings`` und
    ``apps``. Sie ist zwar unsere eigene, aber sie ist die einzige Stelle, an
    der ein Layout von aussen hereinkommt — validiert wird deshalb hier *und*
    in layout_store.save(). Reihenfolge: erst Settings und Apps, dann das
    Layout — das Dashboard baut beim Layout-Ereignis das Deck ohnehin neu.
    """
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as e:
        return SaveResult(False, f"Message is not JSON: {e}")

    if not isinstance(msg, dict):
        return SaveResult(False, "Message is not an object")

    action = msg.get("action")
    if action != "save":
        return SaveResult(False, f"unknown action: {action!r}")

    layout = msg.get("layout")
    if not isinstance(layout, dict):
        return SaveResult(False, "no layout in the message")
    try:
        layout_store.validate(layout)
    except layout_store.LayoutError as e:
        return SaveResult(False, str(e))

    try:
        _save_settings(msg.get("settings"))
        _save_apps(msg.get("apps"))
        layout_store.save(layout)
    except layout_store.LayoutError as e:
        return SaveResult(False, str(e))
    except OSError as e:
        return SaveResult(False, f"Write failed: {e}")

    return SaveResult(True, "Saved — the dashboard picks it up immediately")
