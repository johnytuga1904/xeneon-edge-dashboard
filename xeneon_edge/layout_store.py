"""Persistenz und Validierung von layout.json.

Die Datei sagt, welche Module wo stehen und wie breit sie sind; das
Modul-Register (modules/) sagt, welche es ueberhaupt gibt.

Ungueltiges Layout heisst nie "Dashboard startet nicht". ``load()`` faellt auf
den Default zurueck und sagt im Log, warum — eine Konfigurationsdatei, die den
Bildschirm schwarz laesst, ist auf einem Geraet ohne Tastatur nicht zu
reparieren.
"""
from __future__ import annotations
import json
from typing import Any

from .paths import USER_CONFIG_DIR
from . import modules

LAYOUT_FILE = USER_CONFIG_DIR / "layout.json"

VERSION = 1
FLEX = "flex"

# Das bisher fest verdrahtete Layout aus ui/window.py. Breiten wie gehabt:
# Sensoren 460, Prozesse+Audio 420, Deck 430, Chart nimmt den Rest.
_DEFAULT_PROFILE: dict[str, Any] = {
    "label": "Standard",
    "columns": [
        {"width": 460, "modules": [{"type": "sensors", "config": {}}]},
        {"width": FLEX, "modules": [{"type": "web", "config": {}}]},
        {"width": 420, "modules": [{"type": "processes", "config": {}},
                                   {"type": "audio", "config": {}}]},
        {"width": 430, "modules": [{"type": "deck", "config": {}}]},
    ],
    "topbar": {
        "weather": {"enabled": True, "lat": 47.3464, "lon": 8.2752, "label": ""},
        "match": {"enabled": True, "league": "por.1", "team": "1929"},
    },
}


def default_layout() -> dict[str, Any]:
    return {
        "version": VERSION,
        "active_profile": "default",
        "profiles": {"default": json.loads(json.dumps(_DEFAULT_PROFILE))},
    }


class LayoutError(ValueError):
    """Layout ist unbrauchbar — der Aufrufer nimmt den Default."""


def _validate_column(col: Any, where: str) -> dict[str, Any]:
    if not isinstance(col, dict):
        raise LayoutError(f"{where}: Spalte ist kein Objekt")

    width = col.get("width", FLEX)
    if width != FLEX:
        try:
            width = int(width)
        except (TypeError, ValueError):
            raise LayoutError(f"{where}: Breite '{width}' ist weder Zahl noch '{FLEX}'")
        if width < 80:
            raise LayoutError(f"{where}: Breite {width}px ist zu schmal")

    raw_modules = col.get("modules")
    if not isinstance(raw_modules, list) or not raw_modules:
        raise LayoutError(f"{where}: Spalte ohne Module")

    out_modules = []
    for i, m in enumerate(raw_modules):
        if not isinstance(m, dict):
            raise LayoutError(f"{where}, Modul {i}: kein Objekt")
        type_id = m.get("type")
        if not isinstance(type_id, str) or not type_id:
            raise LayoutError(f"{where}, Modul {i}: kein Typ angegeben")
        config = m.get("config", {})
        if not isinstance(config, dict):
            raise LayoutError(f"{where}, Modul {i}: config ist kein Objekt")
        # Unbekannte Typen sind hier *kein* Fehler: die Datei kann aus einer
        # neueren Version stammen. modules.build() ueberspringt sie einzeln,
        # der Rest des Layouts bleibt benutzbar.
        out_modules.append({"type": type_id, "config": config})

    return {"width": width, "modules": out_modules}


def _validate_profile(profile: Any, name: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise LayoutError(f"Profil '{name}': kein Objekt")

    raw_columns = profile.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise LayoutError(f"Profil '{name}': keine Spalten")

    columns = [_validate_column(c, f"Profil '{name}', Spalte {i}")
               for i, c in enumerate(raw_columns)]

    # Genau eine Flex-Spalte. Keine: das Layout fuellt den Bildschirm nicht.
    # Mehrere: die Aufteilung des Rests waere willkuerlich.
    flex = [i for i, c in enumerate(columns) if c["width"] == FLEX]
    if len(flex) != 1:
        raise LayoutError(
            f"Profil '{name}': genau eine Spalte muss '{FLEX}' sein, gefunden: {len(flex)}"
        )

    topbar = profile.get("topbar", {})
    if not isinstance(topbar, dict):
        raise LayoutError(f"Profil '{name}': topbar ist kein Objekt")

    return {
        "label": str(profile.get("label") or name),
        "columns": columns,
        "topbar": topbar,
    }


def validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise LayoutError("Datei enthaelt kein Objekt")

    version = data.get("version", VERSION)
    if version != VERSION:
        raise LayoutError(f"Version {version} wird nicht unterstuetzt (erwartet {VERSION})")

    raw_profiles = data.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise LayoutError("keine Profile")

    profiles = {name: _validate_profile(p, name) for name, p in raw_profiles.items()}

    active = data.get("active_profile") or next(iter(profiles))
    if active not in profiles:
        raise LayoutError(f"aktives Profil '{active}' existiert nicht")

    return {"version": VERSION, "active_profile": active, "profiles": profiles}


def load() -> dict[str, Any]:
    """Layout aus der Datei, sonst der Default. Wirft nie."""
    if not LAYOUT_FILE.exists():
        return default_layout()
    try:
        raw = json.loads(LAYOUT_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"[xeneon-edge] layout.json nicht lesbar ({e}) — Default-Layout")
        return default_layout()
    try:
        return validate(raw)
    except LayoutError as e:
        print(f"[xeneon-edge] layout.json ungueltig: {e} — Default-Layout")
        return default_layout()


def save(data: dict[str, Any]) -> None:
    """Schreibt validiert und atomar.

    Atomar, weil das Dashboard per FileMonitor an der Datei haengt: ein
    halb geschriebener Stand wuerde sonst als ungueltig gelesen und das
    Layout kurzzeitig auf den Default zuruecksetzen.
    """
    checked = validate(data)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(checked, indent=2, ensure_ascii=False))
    tmp.replace(LAYOUT_FILE)


def active_profile(data: dict[str, Any]) -> dict[str, Any]:
    return data["profiles"][data["active_profile"]]


def migrate_from_settings(settings: dict) -> bool:
    """Beim ersten Start eine layout.json aus den alten Settings bauen.

    Uebernimmt ``chart_url`` ins Web-Modul, damit ein bestehendes Setup nach
    dem Update genau so aussieht wie vorher. Gibt True zurueck, wenn eine
    Datei angelegt wurde.
    """
    if LAYOUT_FILE.exists():
        return False
    data = default_layout()
    chart_url = str(settings.get("chart_url", "") or "")
    if chart_url:
        for column in data["profiles"]["default"]["columns"]:
            for module in column["modules"]:
                if module["type"] == "web":
                    module["config"]["url"] = chart_url
    try:
        save(data)
    except (OSError, LayoutError) as e:
        print(f"[xeneon-edge] layout.json konnte nicht angelegt werden: {e}")
        return False
    print(f"[xeneon-edge] layout.json angelegt: {LAYOUT_FILE}")
    return True
