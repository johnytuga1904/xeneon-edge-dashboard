"""Layout-Editor: Nutzlast fuer die Seite, Auswertung dessen was zurueckkommt.

Die Seite selbst liegt in assets/ und wird von scripts/layout-editor.py in
einem WebKit-Fenster auf dem *Haupt*monitor geoeffnet — am Streifen haengt
keine Tastatur. Dasselbe Muster wie scripts/tradingview-login.py.

Hier steht bewusst nur, was ohne GTK und ohne WebKit testbar ist: die Nutzlast
zusammenbauen und eine Nachricht aus der Seite verarbeiten. Alles, was ein
Fenster braucht, steht im Skript.
"""
from __future__ import annotations
import json
from typing import Any

from . import __name__ as _pkg  # noqa: F401  (nur fuer die Paket-Existenz)
from .. import layout_store, modules, theme
from ..paths import EDITOR_ASSETS_DIR

# Wenn kein Streifen gefunden wird: die Geometrie, fuer die das Dashboard
# entworfen ist. Der Editor muss *irgendeine* Bezugsbreite haben, sonst kann er
# keine Proportionen zeichnen.
FALLBACK_STAGE = {"width": 2560, "height": 720, "connector": ""}


def catalogue() -> list[dict[str, Any]]:
    """Verfuegbare Modultypen fuer die Seitenleiste des Editors."""
    out = []
    for spec in modules.all_specs():
        out.append({
            "type": spec.type_id,
            "label": spec.label,
            "default_width": spec.default_width,
            "singleton": spec.singleton,
            "needs": sorted(spec.needs),
        })
    return out


def payload(stage: dict | None = None, palette: theme.Palette | None = None) -> dict[str, Any]:
    """Alles, was die Seite zum Zeichnen braucht."""
    palette = palette or theme.load(None)
    return {
        "layout": layout_store.load(),
        "catalogue": catalogue(),
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


def handle_message(raw: str) -> SaveResult:
    """Eine Nachricht aus der Seite verarbeiten.

    Die Seite schickt JSON. Sie ist zwar unsere eigene, aber sie ist die
    einzige Stelle, an der ein Layout von aussen hereinkommt — validiert wird
    deshalb hier *und* in layout_store.save().
    """
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as e:
        return SaveResult(False, f"Nachricht ist kein JSON: {e}")

    if not isinstance(msg, dict):
        return SaveResult(False, "Nachricht ist kein Objekt")

    action = msg.get("action")
    if action != "save":
        return SaveResult(False, f"unbekannte Aktion: {action!r}")

    layout = msg.get("layout")
    if not isinstance(layout, dict):
        return SaveResult(False, "kein Layout in der Nachricht")

    try:
        layout_store.save(layout)
    except layout_store.LayoutError as e:
        return SaveResult(False, str(e))
    except OSError as e:
        return SaveResult(False, f"Schreiben fehlgeschlagen: {e}")

    return SaveResult(True, f"Gespeichert: {layout_store.LAYOUT_FILE}")
