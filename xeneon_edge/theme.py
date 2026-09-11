"""Farbpaletten: mitgelieferte themes/*.toml und die aktuelle Omarchy-Palette.

style.css kennt keine Farbwerte mehr, nur Namen (@bg, @accent, ...). Die
Werte kommen aus einer Palette und werden als ``@define-color``-Block vor
das Stylesheet gesetzt — ein Theme-Wechsel ist damit ein Neuladen des
CSS-Providers, kein Neustart.

Das Sondertheme ``omarchy`` liest die colors.toml des gerade aktiven
Omarchy-Themes. Es erscheint nur in der Auswahl, wenn diese Datei existiert;
auf Fedora/KDE fehlt sie und der Eintrag bleibt unsichtbar.
"""
from __future__ import annotations
from dataclasses import dataclass, fields
from pathlib import Path
import re
import tomllib

from .paths import THEMES_DIR

DEFAULT = "crimson"
OMARCHY = "omarchy"
# omarchy-theme-set baut das naechste Theme daneben auf und tauscht dann das
# ganze Verzeichnis "theme" aus; colors.toml darin ist die aktive Palette.
OMARCHY_CURRENT_DIR = Path.home() / ".local" / "state" / "omarchy" / "current"
OMARCHY_COLORS = OMARCHY_CURRENT_DIR / "theme" / "colors.toml"

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Palette:
    id: str
    name: str
    mode: str  # "dark" | "light"
    bg: str
    panel: str
    raised: str
    line: str
    text: str
    muted: str
    label: str
    accent: str
    warm: str
    hot: str
    on_accent: str
    gauge_track: str
    gauge_edge: str

    @property
    def is_light(self) -> bool:
        return self.mode == "light"


COLOR_KEYS = tuple(f.name for f in fields(Palette) if f.name not in ("id", "name", "mode"))


class ThemeError(ValueError):
    pass


def _check_hex(key: str, value: object, where: str) -> str:
    if not isinstance(value, str) or not _HEX.match(value):
        raise ThemeError(f"{where}: '{key}' ist keine #rrggbb-Farbe: {value!r}")
    return value.lower()


def _palette_from(data: dict, *, id: str, where: str) -> Palette:
    missing = [k for k in COLOR_KEYS if k not in data]
    if missing:
        raise ThemeError(f"{where}: fehlende Farben: {', '.join(missing)}")
    colors = {k: _check_hex(k, data[k], where) for k in COLOR_KEYS}
    mode = str(data.get("mode", "dark")).lower()
    if mode not in ("dark", "light"):
        raise ThemeError(f"{where}: mode muss 'dark' oder 'light' sein, nicht {mode!r}")
    return Palette(id=id, name=str(data.get("name") or id), mode=mode, **colors)


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # ValueError deckt TOML- und Unicode-Fehler ab
        raise ThemeError(f"{path}: {e}") from e


# ----- mitgelieferte Paletten -----

def builtin_ids() -> list[str]:
    return sorted(p.stem for p in THEMES_DIR.glob("*.toml"))


def load_builtin(theme_id: str) -> Palette:
    path = THEMES_DIR / f"{theme_id}.toml"
    if not path.exists():
        raise ThemeError(f"Theme '{theme_id}' gibt es nicht ({path})")
    return _palette_from(_read_toml(path), id=theme_id, where=path.name)


# ----- Omarchy -----

def omarchy_available() -> bool:
    return OMARCHY_COLORS.exists()


def load_omarchy() -> Palette:
    """Die Omarchy-Palette auf unsere Schluessel abbilden.

    Omarchy kennt drei Hintergrundstufen und drei Vordergrundstufen; wir
    brauchen Fenster / Panel / erhabene Flaeche und Text / Titel / Sekundaer.
    Die Zuordnung ist so gewaehlt, dass Panels wie bei Crimson eine Spur
    heller als das Fenster sind und Buttons noch eine Spur darueber.
    """
    d = _read_toml(OMARCHY_COLORS)

    def pick(*keys: str) -> str:
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and _HEX.match(v):
                return v
        raise ThemeError(f"{OMARCHY_COLORS}: keiner der Schluessel {keys} gesetzt")

    mode = str(d.get("mode", "dark")).lower()
    if mode == "light":
        # Hell: Fenster ist die helle Grundflaeche, Panels und Buttons werden
        # stufenweise dunkler — sonst verschwinden die Panelkanten.
        bg = pick("background")
        panel = pick("dark_background", "background")
        raised = pick("darker_background", "dark_background", "background")
    else:
        bg = pick("darker_background", "dark_background", "background")
        panel = pick("dark_background", "background")
        raised = pick("background")

    # omarchy-theme-current liest den Namen aus theme.name; das Verzeichnis
    # selbst heisst immer nur "theme".
    name = None
    try:
        raw = (OMARCHY_CURRENT_DIR / "theme.name").read_text(encoding="utf-8").strip()
        name = raw.replace("-", " ").title() or None
    except (OSError, ValueError):
        pass

    data = {
        "bg": bg,
        "panel": panel,
        "raised": raised,
        "line": pick("selection", "lighter_background", "muted"),
        "text": pick("foreground"),
        "muted": pick("muted", "dark_foreground"),
        "label": pick("dark_foreground", "muted", "foreground"),
        "accent": pick("accent", "blue"),
        "warm": pick("yellow", "orange", "accent"),
        "hot": pick("red", "bright_red", "accent"),
        "on_accent": bg,
        "gauge_track": panel,
        "gauge_edge": pick("lighter_background", "selection", "muted"),
        "mode": mode,
        "name": f"Omarchy ({name})" if name else "Omarchy",
    }
    return _palette_from(data, id=OMARCHY, where=str(OMARCHY_COLORS))


# ----- Auswahl -----

def available() -> list[tuple[str, str]]:
    """(id, Anzeigename) aller waehlbaren Themes, Omarchy zuletzt."""
    out: list[tuple[str, str]] = []
    for theme_id in builtin_ids():
        try:
            out.append((theme_id, load_builtin(theme_id).name))
        except ThemeError as e:
            print(f"[xeneon-edge] Theme uebersprungen: {e}")
    if omarchy_available():
        out.append((OMARCHY, "Omarchy (folgt dem System-Theme)"))
    return out


def load(theme_id: str | None) -> Palette:
    """Palette zu einem Theme-Namen; faellt auf den Default zurueck.

    Wirft nie: ein Tippfehler in settings.json darf das Dashboard nicht
    farblos starten lassen.
    """
    theme_id = (theme_id or DEFAULT).strip().lower()
    try:
        if theme_id == OMARCHY:
            return load_omarchy()
        return load_builtin(theme_id)
    except ThemeError as e:
        print(f"[xeneon-edge] Theme '{theme_id}' unbrauchbar ({e}) — {DEFAULT}")
        return load_builtin(DEFAULT)


# ----- Ausgabe -----

def to_css(p: Palette) -> str:
    """Der @define-color-Block, der vor style.css geladen wird."""
    lines = [f"@define-color {k} {getattr(p, k)};" for k in COLOR_KEYS]
    lines += [
        "@define-color accent_dim alpha(@accent, 0.18);",
        "@define-color accent_glow alpha(@accent, 0.55);",
    ]
    return "\n".join(lines) + "\n"


def rgba(hex_color: str, alpha: float) -> str:
    """'#rrggbb' -> 'rgba(r,g,b,a)' fuer HTML-Einbettungen (Widget-Chart)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha:g})"
