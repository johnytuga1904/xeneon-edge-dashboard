"""Modul-Register: was das Dashboard anzeigen *kann*.

Was es tatsaechlich anzeigt, steht in layout.json (siehe layout_store.py).
Diese Trennung ist der ganze Zweck: window.py baut nur noch, was in der
Layout-Datei steht, und muss die einzelnen Panels nicht mehr kennen.

Ein Modul ist ein ``Gtk.Widget`` mit einer ``update(snapshot)``-Methode. Die
Panels in ui/panels.py erfuellen das seit jeher, sie nehmen nur jeweils ihren
eigenen Ausschnitt entgegen (``cpu``, ``ram``, ...) statt den ganzen Snapshot;
die Wrapper in builtin.py gleichen das an.

``needs``, ``schema`` und ``singleton`` werden hier schon deklariert, aber
noch nicht ausgewertet — sie beschreiben das Modul fuer den Editor, der in
Schritt 3 dazukommt:

* ``needs`` sagt, welche Sensor-Subsysteme ein Modul liest. Sobald die
  Metrik-Auswahl steht (Schritt 4), kann der Aggregator ueberspringen, was
  kein sichtbares Modul braucht — wer die Luefter ausblendet, spart das
  hwmon-Polling.
* ``schema`` beschreibt die Einstellungen eines Moduls so, dass der Editor
  daraus ein Formular bauen kann, ohne das Modul zu kennen. Deshalb steht es
  hier und nicht im Editor.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Iterable

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


@dataclass(frozen=True)
class Field:
    """Ein Einstellungsfeld eines Moduls — Bauplan fuer das Editor-Formular."""

    key: str
    label: str
    kind: str  # "text" | "int" | "bool" | "path" | "list"
    default: object = None
    help: str = ""


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


_REGISTRY: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> ModuleSpec:
    if spec.type_id in _REGISTRY:
        raise ValueError(f"Modultyp doppelt registriert: {spec.type_id}")
    _REGISTRY[spec.type_id] = spec
    return spec


def get(type_id: str) -> ModuleSpec | None:
    return _REGISTRY.get(type_id)


def all_specs() -> list[ModuleSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: s.label)


def known_types() -> Iterable[str]:
    return _REGISTRY.keys()


def build(type_id: str, config: dict | None = None) -> Gtk.Widget | None:
    """Widget fuer einen Modultyp bauen, oder None bei unbekanntem Typ.

    Unbekannt heisst in der Praxis: die Layout-Datei stammt aus einer neueren
    Version. Das ist kein Grund, das ganze Dashboard nicht zu starten — der
    Aufrufer laesst den Platz einfach leer.
    """
    spec = _REGISTRY.get(type_id)
    if spec is None:
        print(f"[xeneon-edge] unbekannter Modultyp '{type_id}' — wird uebersprungen")
        return None
    try:
        return spec.factory(dict(config or {}))
    except Exception as e:
        print(f"[xeneon-edge] Modul '{type_id}' liess sich nicht bauen: {e}")
        return None


# Registriert die mitgelieferten Module. Ganz unten, weil builtin.py aus
# diesem Modul importiert.
from . import builtin  # noqa: E402,F401
