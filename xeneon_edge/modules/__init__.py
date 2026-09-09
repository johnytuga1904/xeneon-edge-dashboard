"""Modul-Register: was das Dashboard anzeigen *kann*.

Was es tatsaechlich anzeigt, steht in layout.json (siehe layout_store.py).
Diese Trennung ist der ganze Zweck: window.py baut nur noch, was in der
Layout-Datei steht, und muss die einzelnen Panels nicht mehr kennen.

Zwei Register: Spalten-Module (Sensoren, Prozesse, Web, Deck, ...) und
Topbar-Widgets (Marke, Uhr, Wetter, ...). Beide beschreiben sich mit
derselben ``ModuleSpec``; ein Widget ist ein ``Gtk.Widget`` mit
``update(snapshot)`` und optional ``tick()`` (jede Sekunde, fuer die Uhr
und die Statuspille).

* ``needs`` sagt, welche Sensor-Subsysteme ein Modul liest; der Aggregator
  ueberspringt, was kein sichtbares Modul braucht.
* ``schema`` beschreibt die Einstellungen so, dass der Editor daraus ein
  Formular bauen kann, ohne das Modul zu kennen. Deshalb steht es hier und
  nicht im Editor.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


@dataclass(frozen=True)
class Field:
    """Ein Einstellungsfeld eines Moduls — Bauplan fuer das Editor-Formular.

    ``kind``: "text" | "int" | "float" | "bool" | "list" | "select".
    ``options`` (fuer list/select): (wert, anzeige)-Paare.
    """

    key: str
    label: str
    kind: str
    default: object = None
    help: str = ""
    options: tuple[tuple[str, str], ...] = ()
    min: float | None = None
    max: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "kind": self.kind,
            "default": self.default, "help": self.help,
            "options": [list(o) for o in self.options],
            "min": self.min, "max": self.max,
        }


@dataclass(frozen=True)
class ModuleSpec:
    type_id: str
    label: str
    factory: Callable[[dict], Gtk.Widget]
    needs: frozenset[str] = frozenset()
    schema: tuple[Field, ...] = ()
    default_width: int | None = None
    # Module, von denen es sinnvoll nur eines geben kann. Das Deck haelt
    # Autostart-Zustand und wird von app.py gesucht; zwei davon waeren
    # mehrdeutig.
    singleton: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_id, "label": self.label,
            "default_width": self.default_width, "singleton": self.singleton,
            "needs": sorted(self.needs),
            "schema": [f.to_dict() for f in self.schema],
        }


_REGISTRY: dict[str, ModuleSpec] = {}
_TOPBAR: dict[str, ModuleSpec] = {}


def _register(registry: dict[str, ModuleSpec], spec: ModuleSpec) -> ModuleSpec:
    if spec.type_id in registry:
        raise ValueError(f"Modultyp doppelt registriert: {spec.type_id}")
    registry[spec.type_id] = spec
    return spec


def register(spec: ModuleSpec) -> ModuleSpec:
    return _register(_REGISTRY, spec)


def register_topbar(spec: ModuleSpec) -> ModuleSpec:
    return _register(_TOPBAR, spec)


def get(type_id: str) -> ModuleSpec | None:
    return _REGISTRY.get(type_id)


def get_topbar(type_id: str) -> ModuleSpec | None:
    return _TOPBAR.get(type_id)


def all_specs() -> list[ModuleSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: s.label)


def all_topbar_specs() -> list[ModuleSpec]:
    return sorted(_TOPBAR.values(), key=lambda s: s.label)


def known_types() -> Iterable[str]:
    return _REGISTRY.keys()


def _build(registry: dict[str, ModuleSpec], what: str,
           type_id: str, config: dict | None) -> Gtk.Widget | None:
    """Widget bauen, oder None bei unbekanntem Typ.

    Unbekannt heisst in der Praxis: die Layout-Datei stammt aus einer neueren
    Version. Das ist kein Grund, das ganze Dashboard nicht zu starten — der
    Aufrufer laesst den Platz einfach leer.
    """
    spec = registry.get(type_id)
    if spec is None:
        print(f"[xeneon-edge] unbekannter {what} '{type_id}' — wird uebersprungen")
        return None
    try:
        return spec.factory(dict(config or {}))
    except Exception as e:
        print(f"[xeneon-edge] {what} '{type_id}' liess sich nicht bauen: {e}")
        return None


def build(type_id: str, config: dict | None = None) -> Gtk.Widget | None:
    return _build(_REGISTRY, "Modultyp", type_id, config)


def build_topbar(type_id: str, config: dict | None = None) -> Gtk.Widget | None:
    return _build(_TOPBAR, "Topbar-Widget", type_id, config)


# Registriert die mitgelieferten Module. Ganz unten, weil builtin.py aus
# diesem Modul importiert.
from . import builtin  # noqa: E402,F401
