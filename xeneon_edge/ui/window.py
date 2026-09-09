"""Main window: topbar + column grid, both built from layout.json."""
from __future__ import annotations
import json
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib  # noqa: E402

from .layout import FixedWidth, WeightedColumn
from .topbar import ActionsWidget
from .. import layout_store, modules


def _weights(entries: list[dict]) -> list[float | None]:
    """Hoehenanteile der Module einer Spalte; ohne Angaben None (natuerlich)."""
    raw = [float(e.get("height") or 0) for e in entries]
    if not any(raw):
        return [None] * len(entries)
    default = 100.0 / max(1, len(entries))
    return [w if w > 0 else default for w in raw]

# Spaltenbreiten stehen in layout.json, nicht mehr hier. FixedWidth meldet sie
# als Minimum *und* Natural, damit kein Wert im Inneren die Spalte verschieben
# kann; genau eine Spalte ist "flex" und nimmt den Rest.


def _module_key(kind: str, type_id: str, config: dict) -> tuple[str, str, str]:
    """Identitaet eines Widgets ueber einen Rebuild hinweg: Art + Typ + Konfiguration.

    Schluessel mit Unterstrich (``_palette``) sind Laufzeitbeigaben, keine
    Konfiguration, und bleiben aussen vor.
    """
    public = {k: v for k, v in config.items() if not str(k).startswith("_")}
    return kind, type_id, json.dumps(public, sort_keys=True, default=str)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, *, on_open_settings, palette=None):
        super().__init__(application=app)
        # Aktive Palette — Web-Module bekommen sie beim Bau, damit das
        # TradingView-Widget in denselben Farben startet wie der Rest.
        self._palette = palette
        self.set_default_size(1480, 900)
        self.set_title("Xeneon Edge Dashboard")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(6); outer.set_margin_bottom(6)
        outer.set_margin_start(6); outer.set_margin_end(6)
        self.set_content(outer)

        # ----- Topbar: drei Slots laut layout.json, ganz rechts fest die Aktionen
        # CenterBox: der mittlere Slot bleibt exakt mittig, egal wie breit die
        # aeusseren werden.
        topbar = Gtk.CenterBox()
        topbar.set_hexpand(True)
        outer.append(topbar)
        self._slots: dict[str, Gtk.Box] = {}
        for slot, spacing in (("left", 10), ("center", 14), ("right", 10)):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
            self._slots[slot] = box
        self._slots["center"].set_halign(Gtk.Align.CENTER)
        topbar.set_start_widget(self._slots["left"])
        topbar.set_center_widget(self._slots["center"])
        end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        end.append(self._slots["right"])
        end.append(ActionsWidget(on_open_settings=on_open_settings,
                                 on_toggle_fullscreen=self._toggle_fullscreen,
                                 on_close=self.close))
        topbar.set_end_widget(end)

        # ----- Hauptgitter: eine Zeile, Spalten laut layout.json -----
        # Der Halter bleibt im Fenster stehen; apply_layout() tauscht nur sein
        # Kind, damit ein Layout-Wechsel den Rest des Fensters nicht anfasst.
        self.grid_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.grid_holder.set_hexpand(True)
        self.grid_holder.set_vexpand(True)
        outer.append(self.grid_holder)

        # Gebaute Widgets (Spalten-Module und Topbar) in Layout-Reihenfolge.
        # apply_snapshot() geht diese Liste durch, statt feste Attribute
        # anzusprechen — nach einem Rebuild zeigt sie auf die neuen Widgets.
        self._modules: list[Gtk.Widget] = []
        self._widgets: list[Gtk.Widget] = []
        # (Widget, Schluessel) des aktuellen Stands — der Vorrat, aus dem
        # apply_layout() beim naechsten Rebuild unveraenderte Widgets holt.
        self._keys: list[tuple[Gtk.Widget, tuple]] = []
        # Sensor-Subsysteme, die die sichtbaren Module brauchen (Aggregator),
        # und was die Topbar aus dem Netz will (Wetter, Spiel).
        self.needs: frozenset[str] = frozenset()
        self.feeds: dict = {}

        self.apply_layout(layout_store.load())

        # Uhr und Statuspille ticken auch ohne Sensordaten — ein toter
        # Sensor-Thread muss als STALE sichtbar werden.
        GLib.timeout_add_seconds(1, self._tick)

    # ----- layout -----

    def apply_layout(self, layout: dict) -> None:
        """Topbar und Gitter aus einem Layout neu bauen.

        Laeuft auf dem GTK-Main-Loop, und apply_snapshot() greift nur ueber
        self._widgets zu — ein Rebuild kann also keine Aktualisierung auf einem
        bereits abgeraeumten Widget hinterlassen.

        Widgets, deren Typ und Konfiguration unveraendert sind, wandern aus dem
        alten Stand in den neuen statt neu gebaut zu werden. Fuer das Web-Modul
        ist das der Unterschied zwischen "Spalte rutscht" und "Chart laedt
        mehrere Sekunden neu" — und das Deck behaelt seinen Zustand.
        """
        profile = layout_store.active_profile(layout)

        pool: dict[tuple, list[Gtk.Widget]] = {}
        for widget, key in self._keys:
            pool.setdefault(key, []).append(widget)

        modules_built: list[Gtk.Widget] = []
        widgets: list[Gtk.Widget] = []
        keys: list[tuple[Gtk.Widget, tuple]] = []
        needs: set[str] = set()
        feeds: dict = {}

        def take(kind: str, type_id: str, config: dict) -> Gtk.Widget | None:
            key = _module_key(kind, type_id, config)
            reusable = pool.get(key)
            if reusable:
                widget = reusable.pop(0)
                parent = widget.get_parent()
                if parent is not None:
                    parent.remove(widget)
            else:
                config = dict(config)
                config["_palette"] = self._palette
                build = modules.build_topbar if kind == "topbar" else modules.build
                widget = build(type_id, config)
                if widget is None:
                    return None
            widgets.append(widget)
            keys.append((widget, key))
            return widget

        # Topbar: Slots leeren, dann laut Layout fuellen
        for slot, box in self._slots.items():
            child = box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                box.remove(child)
                child = nxt
            for entry in profile["topbar"].get(slot, []):
                widget = take("topbar", entry["type"], entry.get("config") or {})
                if widget is None:
                    continue
                box.append(widget)
                for name, cfg in (getattr(widget, "feeds", None) or {}).items():
                    feeds.setdefault(name, cfg)

        # Spalten
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.set_column_homogeneous(False)

        for index, column in enumerate(profile["columns"]):
            # WeightedColumn statt Gtk.Box: verteilt die Hoehe nach den
            # Anteilen aus layout.json ("height"), ohne Angaben gleich.
            box = WeightedColumn(spacing=6)
            weights = _weights(column["modules"])

            for entry, weight in zip(column["modules"], weights):
                type_id = entry["type"]
                widget = take("module", type_id, entry.get("config") or {})
                if widget is None:
                    continue
                widget.set_vexpand(True)
                widget.set_hexpand(True)
                box.add(widget, weight)
                modules_built.append(widget)
                spec = modules.get(type_id)
                needs |= getattr(widget, "needs", spec.needs if spec else frozenset())

            if column["width"] == layout_store.FLEX:
                box.set_hexpand(True)
                grid.attach(box, index, 0, 1, 1)
            else:
                # Nicht um Breite mit der Flex-Spalte konkurrieren.
                box.set_hexpand(False)
                grid.attach(FixedWidth(box, column["width"]), index, 0, 1, 1)

        old = self.grid_holder.get_first_child()
        if old is not None:
            self.grid_holder.remove(old)
        self.grid_holder.append(grid)
        self._modules = modules_built
        self._widgets = widgets
        self._keys = keys
        self.needs = frozenset(needs)
        self.feeds = feeds
        self._layout = layout
        self._tick()

    def find_module(self, type_id: str) -> Gtk.Widget | None:
        """Erstes gebautes Modul eines Typs — fuer app.py, das das Deck befuellt."""
        spec = modules.get(type_id)
        if spec is None:
            return None
        for widget in self._modules:
            if isinstance(widget, spec.factory):
                return widget
        return None

    def _toggle_fullscreen(self, *_args) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _tick(self) -> bool:
        for widget in self._widgets:
            tick = getattr(widget, "tick", None)
            if tick is None:
                continue
            try:
                tick()
            except Exception as e:
                print(f"[xeneon-edge] Widget {type(widget).__name__} tick: {e}")
        return True

    # ----- snapshot push -----

    def apply_snapshot(self, snap) -> None:
        # Ueber die Liste, nicht ueber feste Attribute: nach apply_layout()
        # zeigt sie auf die aktuellen Widgets. Ein Widget, das sich
        # verschluckt, darf die uebrigen nicht mitreissen.
        for widget in self._widgets:
            update = getattr(widget, "update", None)
            if update is None:
                continue
            try:
                update(snap)
            except Exception as e:
                print(f"[xeneon-edge] Widget {type(widget).__name__} update: {e}")

    def populate_deck(self, apps: list[dict], macros: list[dict], *,
                      hold_to_confirm: bool, isolate: bool = True,
                      app_slots: int = 9) -> None:
        deck = self.find_module("deck")
        if deck is None:
            return
        deck.populate(apps, macros, hold_to_confirm=hold_to_confirm,
                      isolate=isolate, app_slots=app_slots)

    def apply_palette(self, palette) -> None:
        """Theme-Wechsel zur Laufzeit: Widgets, die Farben selbst rendern, informieren."""
        self._palette = palette
        for widget in self._widgets:
            hook = getattr(widget, "set_palette", None)
            if hook is not None:
                try:
                    hook(palette)
                except Exception as e:
                    print(f"[xeneon-edge] Widget {type(widget).__name__} set_palette: {e}")
