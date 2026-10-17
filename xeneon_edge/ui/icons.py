"""Resolve a Gio.Icon for a launch-deck entry.

Lookup order:
1. Explicit `icon` field in apps.json — mitgeliefertes Icon (``llm-start``),
   absoluter Dateipfad, oder Name aus dem Icon-Theme
2. Macro id keyword match (shutdown, restart, suspend, lock, …)
3. Match command basename to a known DesktopAppInfo (.desktop file)
4. Try the command basename directly as an icon-theme name
5. Fall back to "application-x-executable-symbolic"

``bundled_gicon`` ist der kleine Bruder fuer feste Tasten (Wiedergabe): nur
mitgeliefertes Icon oder Theme-Name, ohne die Deck-Heuristik.

Namen aus dem Theme werden vor der Rueckgabe geprueft. Ohne diese Pruefung
liefert Schritt 4 fuer jedes Shell-Script einen Namen wie
``g1_lfm2-5-2-6b-f16_96k.sh``, den kein Theme kennt — GTK zeigt dann fuer
saemtliche Script-Macros dasselbe "kein Eintrag"-Symbol.
"""
from __future__ import annotations
from pathlib import Path
import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gdk, Gtk  # noqa: E402

from ..paths import ICONS_DIR


_MACRO_BUILTIN_ICONS: dict[str, str] = {
    "shutdown":  "system-shutdown-symbolic",
    "poweroff":  "system-shutdown-symbolic",
    "restart":   "system-reboot-symbolic",
    "reboot":    "system-reboot-symbolic",
    "sleep":     "system-suspend-symbolic",
    "suspend":   "system-suspend-symbolic",
    "hibernate": "system-hibernate-symbolic",
    "lock":      "system-lock-screen-symbolic",
    "logout":    "system-log-out-symbolic",
    "ksysguard": "utilities-system-monitor-symbolic",
    "ramflush":  "drive-harddisk-symbolic",
    "kquitapp":  "view-refresh-symbolic",
    "explrst":   "view-refresh-symbolic",
}

_FALLBACK_APP   = "application-x-executable-symbolic"
_FALLBACK_MACRO = "system-run-symbolic"


def _theme_has(name: str) -> bool:
    """Kennt das Icon-Theme diesen Namen? Ohne Display: nein."""
    if not name:
        return False
    display = Gdk.Display.get_default()
    if display is None:
        return False
    return Gtk.IconTheme.get_for_display(display).has_icon(name)


def _bundled(value: str) -> Path | None:
    """Mitgeliefertes Icon per Dateiname, mit und ohne Endung/-symbolic."""
    for candidate in (value, f"{value}.svg", f"{value}-symbolic.svg"):
        p = ICONS_DIR / candidate
        if p.is_file():
            return p
    return None


def _icon_from_name_or_path(value: str) -> Gio.Icon | None:
    if not value:
        return None
    p = Path(value).expanduser()
    if p.is_absolute() and p.is_file():
        return Gio.FileIcon.new(Gio.File.new_for_path(str(p)))
    bundled = _bundled(value)
    if bundled is not None:
        return Gio.FileIcon.new(Gio.File.new_for_path(str(bundled)))
    # Nur zurueckgeben, was das Theme auch hat — sonst faellt resolve_icon
    # weiter durch, statt ein kaputtes Icon zu liefern.
    return Gio.ThemedIcon.new(value) if _theme_has(value) else None


def bundled_gicon(name: str) -> Gio.Icon:
    """Mitgeliefertes Icon zuerst, der gleichnamige Theme-Eintrag als Reserve.

    Fuer feste Tasten (Wiedergabe), nicht fuer Deck-Eintraege: dort sucht
    ``resolve_icon`` weiter. Hier gibt es keinen dritten Weg, also kommt
    notfalls der Theme-Name zurueck — kennt das Theme ihn nicht, zeigt GTK
    das "kein Eintrag"-Symbol, so wie bisher.
    """
    bundled = _bundled(name)
    if bundled is not None:
        return Gio.FileIcon.new(Gio.File.new_for_path(str(bundled)))
    return Gio.ThemedIcon.new(name)


def _command_basename(entry: dict) -> str:
    cmd = (entry.get("command") or "").strip()
    if not cmd:
        return ""
    return Path(cmd).name.lower()


def _from_desktop_app_info(cmd_basename: str) -> Gio.Icon | None:
    if not cmd_basename:
        return None
    for app in Gio.AppInfo.get_all():
        exe = (app.get_executable() or "")
        if not exe:
            continue
        if Path(exe).name.lower() == cmd_basename:
            icon = app.get_icon()
            if icon is not None:
                return icon
    return None


def resolve_icon(entry: dict) -> Gio.Icon:
    # 1. explicit override
    explicit = entry.get("icon")
    if explicit:
        ic = _icon_from_name_or_path(explicit)
        if ic is not None:
            return ic

    eid = (entry.get("id") or "").lower()
    kind = (entry.get("kind") or "").lower()

    # 2. macro keyword match
    if eid in _MACRO_BUILTIN_ICONS:
        return Gio.ThemedIcon.new(_MACRO_BUILTIN_ICONS[eid])

    cmd_base = _command_basename(entry)

    # 3. DesktopAppInfo
    ic = _from_desktop_app_info(cmd_base)
    if ic is not None:
        return ic

    # 4. command basename as icon-theme name — nur wenn es das Theme kennt
    if _theme_has(cmd_base):
        return Gio.ThemedIcon.new_with_default_fallbacks(cmd_base)

    # 5. category fallback
    return Gio.ThemedIcon.new(_FALLBACK_MACRO if kind == "macro" else _FALLBACK_APP)
