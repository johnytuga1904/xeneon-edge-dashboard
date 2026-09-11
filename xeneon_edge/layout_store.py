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
from . import modules  # noqa: F401 — laedt das Modul-Register vor validate()

LAYOUT_FILE = USER_CONFIG_DIR / "layout.json"

# Version 2: die Topbar besteht aus drei Slots (links, Mitte, rechts) mit
# Widgets wie die Spalten aus Modulen. Version 1 hatte dort nur
# {"weather": {...}, "match": {...}} und wird beim Laden umgebaut.
# Version 3: TradingView ist ein eigenes Modul. Bis 2 war das Web-Panel
# beides — leere Adresse hiess "TradingView-Widget". Beides wird beim Laden
# umgebaut, aeltere Dateien bleiben also lesbar.
VERSION = 3
FLEX = "flex"
TOPBAR_SLOTS = ("left", "center", "right")

# Das bisher fest verdrahtete Layout aus ui/window.py. Breiten wie gehabt:
# Sensoren 460, Prozesse+Audio 420, Deck 430, Chart nimmt den Rest. Die
# Topbar hat bewusst weder Wetter noch Spiel: beides braucht einen Standort
# bzw. ein Team, und die des Autors sind kein sinnvoller Default.
_DEFAULT_PROFILE: dict[str, Any] = {
    "label": "Standard",
    "columns": [
        {"width": 460, "modules": [{"type": "sensors", "config": {}}]},
        {"width": FLEX, "modules": [{"type": "tradingview", "config": {}}]},
        {"width": 420, "modules": [{"type": "processes", "config": {}},
                                   {"type": "audio", "config": {}}]},
        {"width": 430, "modules": [{"type": "deck", "config": {}}]},
    ],
    "topbar": {
        "left": [{"type": "brand", "config": {}}, {"type": "status", "config": {}},
                 {"type": "net", "config": {}}],
        "center": [{"type": "clock", "config": {}}],
        "right": [],
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
        entry: dict[str, Any] = {"type": type_id, "config": config}
        # Hoehenanteil in Prozent, nur sinnvoll bei mehreren Modulen in der
        # Spalte. Fehlt er, teilen sich die Module die Hoehe gleich.
        if m.get("height") is not None:
            try:
                height = int(m["height"])
            except (TypeError, ValueError):
                raise LayoutError(f"{where}, Modul {i}: height '{m['height']}' ist keine Zahl")
            if not 5 <= height <= 95:
                raise LayoutError(f"{where}, Modul {i}: height {height} liegt nicht in 5..95")
            entry["height"] = height
        out_modules.append(entry)

    return {"width": width, "modules": out_modules}


def _validate_entries(raw: Any, where: str) -> list[dict[str, Any]]:
    """[{type, config}]-Liste, wie sie Spalten und Topbar-Slots enthalten."""
    if not isinstance(raw, list):
        raise LayoutError(f"{where}: keine Liste")
    out = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise LayoutError(f"{where}, Eintrag {i}: kein Objekt")
        type_id = m.get("type")
        if not isinstance(type_id, str) or not type_id:
            raise LayoutError(f"{where}, Eintrag {i}: kein Typ angegeben")
        config = m.get("config", {})
        if not isinstance(config, dict):
            raise LayoutError(f"{where}, Eintrag {i}: config ist kein Objekt")
        out.append({"type": type_id, "config": config})
    return out


def _module_from_v2(module: Any) -> Any:
    """Ein Web-Modul der Version 2 auf das TradingView-Modul umlegen.

    Bis Version 2 hiess "Web-Panel ohne Adresse" das eingebettete
    TradingView-Widget und "Web-Panel mit tradingview.com-Adresse" der eigene
    Chart. Ohne diesen Umbau zeigte ein bestehendes Layout nach dem Update
    einen leeren Kasten, wo vorher der Chart stand.
    """
    if not isinstance(module, dict) or module.get("type") != "web":
        return module
    raw_config = module.get("config")
    config = dict(raw_config) if isinstance(raw_config, dict) else {}
    url = str(config.get("url") or "")
    if url and "tradingview.com" not in url:
        return module          # ein echtes Web-Panel, bleibt eines
    config.pop("url", None)
    if url:
        config["mode"] = "account"
        config["url"] = url
    else:
        config["mode"] = "widget"
    return {**module, "type": "tradingview", "config": config}


def _profiles_from_v2(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    out = {}
    for name, profile in raw.items():
        if not isinstance(profile, dict) or not isinstance(profile.get("columns"), list):
            out[name] = profile
            continue
        columns = []
        for column in profile["columns"]:
            if isinstance(column, dict) and isinstance(column.get("modules"), list):
                column = {**column,
                          "modules": [_module_from_v2(m) for m in column["modules"]]}
            columns.append(column)
        out[name] = {**profile, "columns": columns}
    return out


def _topbar_from_v1(old: Any) -> dict[str, Any]:
    """Topbar der Version 1 ({"weather": {...}, "match": {...}}) umbauen.

    Was eingeschaltet war, bleibt an seinem Platz; die drei festen Pillen
    links kommen dazu. So sieht ein Dashboard nach dem Update aus wie vorher.
    """
    old = old if isinstance(old, dict) else {}
    center: list[dict[str, Any]] = []
    weather = old.get("weather") or {}
    if isinstance(weather, dict) and weather.get("enabled", True) \
            and weather.get("lat") is not None and weather.get("lon") is not None:
        center.append({"type": "weather", "config": {
            "lat": weather["lat"], "lon": weather["lon"],
            "label": str(weather.get("label") or "")}})
    center.append({"type": "clock", "config": {}})
    match = old.get("match") or {}
    if isinstance(match, dict) and match.get("enabled") \
            and match.get("league") and match.get("team"):
        team = str(match["team"])
        center.append({"type": "match", "config": {
            "league": str(match["league"]), "team": team,
            # Das Kuerzel gab es in Version 1 noch nicht; im Editor nachtragen.
            "short": ""}})
    return {
        "left": [{"type": "brand", "config": {}}, {"type": "status", "config": {}},
                 {"type": "net", "config": {}}],
        "center": center,
        "right": [],
    }


def _validate_topbar(raw: Any, name: str) -> dict[str, Any]:
    if raw is None:
        return json.loads(json.dumps(_DEFAULT_PROFILE["topbar"]))
    if not isinstance(raw, dict):
        raise LayoutError(f"Profil '{name}': topbar ist kein Objekt")
    if not any(slot in raw for slot in TOPBAR_SLOTS):
        return _topbar_from_v1(raw)
    return {slot: _validate_entries(raw.get(slot, []), f"Profil '{name}', Topbar {slot}")
            for slot in TOPBAR_SLOTS}


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

    return {
        "label": str(profile.get("label") or name),
        "columns": columns,
        "topbar": _validate_topbar(profile.get("topbar"), name),
    }


def validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise LayoutError("Datei enthaelt kein Objekt")

    version = data.get("version", VERSION)
    if version not in (1, 2, VERSION):
        raise LayoutError(f"Version {version} wird nicht unterstuetzt (erwartet {VERSION})")

    raw_profiles = data.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise LayoutError("keine Profile")

    if version in (1, 2):
        raw_profiles = _profiles_from_v2(raw_profiles)

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
                if module["type"] == "tradingview":
                    module["config"].update({"mode": "account", "url": chart_url})
    try:
        save(data)
    except (OSError, LayoutError) as e:
        print(f"[xeneon-edge] layout.json konnte nicht angelegt werden: {e}")
        return False
    print(f"[xeneon-edge] layout.json angelegt: {LAYOUT_FILE}")
    return True
