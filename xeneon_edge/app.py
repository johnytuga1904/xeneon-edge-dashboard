"""Adw.Application entry point."""
from __future__ import annotations
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Gio, Adw, GLib  # noqa: E402

from .paths import STYLE_CSS
from . import theme as theme_mod
from .sensors import Aggregator
from .ui.window import MainWindow
from .ui.settings import SettingsDialog
from .ui.monitors import find_target_monitor, describe
from . import config_store, layout_store

# Der Omarchy-Symlink wird beim Theme-Wechsel mehrfach angefasst — buendeln.
_THEME_RELOAD_DELAY_MS = 300


class XeneonEdgeApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="ch.xeneon.edge")
        self._aggregator: Aggregator | None = None
        self._window: MainWindow | None = None
        self._layout_monitor: Gio.FileMonitor | None = None
        self._layout_reload_id: int | None = None
        self._css_provider: Gtk.CssProvider | None = None
        self._palette: theme_mod.Palette | None = None
        self._theme_id: str = theme_mod.DEFAULT
        self._omarchy_monitor: Gio.FileMonitor | None = None
        self._theme_reload_id: int | None = None

    def do_startup(self):  # type: ignore[override]
        Adw.Application.do_startup(self)
        self._theme_id = str(config_store.load_settings().get("theme") or theme_mod.DEFAULT)
        self._palette = theme_mod.load(self._theme_id)
        self._load_css()
        self._watch_omarchy()

    def do_activate(self):  # type: ignore[override]
        if self._window is not None:
            self._window.present()
            return
        # Bestehende Installationen haben noch keine layout.json — aus den
        # Settings eine bauen, damit das Dashboard nach dem Update unveraendert
        # aussieht (chart_url wandert ins Web-Modul).
        layout_store.migrate_from_settings(config_store.load_settings())

        self._window = MainWindow(self, on_open_settings=self._open_settings,
                                  palette=self._palette)
        self._refresh_deck()
        self._watch_layout()
        self._window.present()
        self._target_monitor()

        # Sensor aggregator pushes snapshots through GLib.idle_add to the UI
        def on_snapshot(snap):
            GLib.idle_add(self._window.apply_snapshot, snap)

        self._aggregator = Aggregator(on_snapshot=on_snapshot, interval=1.0,
                                      needs=self._window.needs)
        self._aggregator.start()

    def do_shutdown(self):  # type: ignore[override]
        if self._aggregator is not None:
            self._aggregator.stop()
        if self._layout_reload_id is not None:
            GLib.source_remove(self._layout_reload_id)
        if self._layout_monitor is not None:
            self._layout_monitor.cancel()
        if self._theme_reload_id is not None:
            GLib.source_remove(self._theme_reload_id)
        if self._omarchy_monitor is not None:
            self._omarchy_monitor.cancel()
        Adw.Application.do_shutdown(self)

    # --------

    def _watch_layout(self) -> None:
        """layout.json beobachten und das Gitter bei Aenderung neu bauen.

        Auf die Datei zu horchen statt auf den Editor zu warten heisst: jeder
        Weg wirkt gleich — der Editor, ein Texteditor, ein Konfig-Werkzeug.
        """
        try:
            gfile = Gio.File.new_for_path(str(layout_store.LAYOUT_FILE))
            monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        except Exception as e:
            print(f"[xeneon-edge] layout.json wird nicht beobachtet: {e}")
            return
        monitor.connect("changed", self._on_layout_changed)
        self._layout_monitor = monitor

    def _on_layout_changed(self, _monitor, _f, _other, event_type) -> None:
        """Ein Speichervorgang meldet sich mehrfach — zu einem Rebuild buendeln.

        layout_store.save() schreibt in eine Temp-Datei und benennt sie um.
        Der Monitor sieht dadurch pro Speichern *zwei* Ereignisse (CREATED,
        dann CHANGES_DONE_HINT); ungebremst wuerde das Gitter zweimal
        hintereinander neu gebaut und sichtbar flackern.
        """
        if event_type not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                              Gio.FileMonitorEvent.MOVED_IN,
                              Gio.FileMonitorEvent.CREATED):
            return
        if self._layout_reload_id is not None:
            GLib.source_remove(self._layout_reload_id)
        self._layout_reload_id = GLib.timeout_add(250, self._reload_layout)

    def _reload_layout(self) -> bool:
        self._layout_reload_id = None
        if self._window is None:
            return False
        print("[xeneon-edge] layout.json geaendert — Gitter wird neu gebaut")
        self._window.apply_layout(layout_store.load())
        if self._aggregator is not None:
            self._aggregator.set_needs(self._window.needs)
        # Das Deck ist frisch gebaut und damit leer — oder wiederverwendet;
        # populate() ist in beiden Faellen richtig.
        self._refresh_deck()
        return False

    # --------

    def _load_css(self) -> None:
        """Palette + style.css in *einen* Provider laden.

        Ein Provider statt zwei, weil ein Theme-Wechsel dann nur ein
        ``load_from_string`` ist: GTK wirft den alten Stand komplett weg und
        rechnet die Styles neu — kein Neustart, kein zweiter Provider, der mit
        dem ersten um Prioritaeten streitet.
        """
        palette = self._palette or theme_mod.load(None)
        try:
            css = theme_mod.to_css(palette) + STYLE_CSS.read_text()
        except OSError as e:
            print(f"[xeneon-edge] CSS load failed: {e}")
            return
        if self._css_provider is None:
            self._css_provider = Gtk.CssProvider()
            display = Gdk.Display.get_default()
            if display is None:
                return
            Gtk.StyleContext.add_provider_for_display(
                display, self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        try:
            self._css_provider.load_from_string(css)
        except Exception as e:
            print(f"[xeneon-edge] CSS load failed: {e}")
        # libadwaita-Dialoge (Settings) folgen der Helligkeit der Palette.
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if palette.is_light else Adw.ColorScheme.FORCE_DARK
        )

    # ----- Theme -----

    def apply_theme(self, theme_id: str | None) -> None:
        """Theme aus den Settings uebernehmen — live, ohne Neustart."""
        theme_id = str(theme_id or theme_mod.DEFAULT)
        self._theme_id = theme_id
        self._palette = theme_mod.load(theme_id)
        print(f"[xeneon-edge] Theme: {self._palette.name}")
        self._load_css()
        if self._window is not None:
            self._window.apply_palette(self._palette)
        self._watch_omarchy()

    def _watch_omarchy(self) -> None:
        """Bei Theme "omarchy" dem Theme-Wechsel folgen.

        omarchy-theme-set tauscht das ganze Verzeichnis current/theme aus
        statt Dateien darin zu aendern. Beobachtet wird deshalb das
        Verzeichnis darueber — ein Monitor auf colors.toml selbst wuerde mit
        dem alten Verzeichnis verschwinden und nie wieder feuern.
        """
        want = self._theme_id == theme_mod.OMARCHY
        if not want:
            if self._omarchy_monitor is not None:
                self._omarchy_monitor.cancel()
                self._omarchy_monitor = None
            return
        if self._omarchy_monitor is not None:
            return
        try:
            gdir = Gio.File.new_for_path(str(theme_mod.OMARCHY_CURRENT_DIR))
            monitor = gdir.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        except Exception as e:
            print(f"[xeneon-edge] Omarchy-Theme wird nicht beobachtet: {e}")
            return
        monitor.connect("changed", self._on_omarchy_changed)
        self._omarchy_monitor = monitor

    def _on_omarchy_changed(self, _monitor, _f, _other, _event_type) -> None:
        if self._theme_reload_id is not None:
            GLib.source_remove(self._theme_reload_id)
        self._theme_reload_id = GLib.timeout_add(_THEME_RELOAD_DELAY_MS, self._reload_omarchy)

    def _reload_omarchy(self) -> bool:
        self._theme_reload_id = None
        if self._theme_id == theme_mod.OMARCHY:
            self.apply_theme(theme_mod.OMARCHY)
        return False

    def _refresh_deck(self) -> None:
        if self._window is None:
            return
        settings = config_store.load_settings()
        apps_data = config_store.load_apps()
        app_slots, _ = config_store.deck_split(settings)
        self._window.populate_deck(
            apps_data.get("apps", []),
            apps_data.get("macros", []),
            hold_to_confirm=settings.get("hold_to_confirm", True),
            isolate=settings.get("isolate_launches", True),
            app_slots=app_slots,
        )

    def _open_settings(self) -> None:
        if self._window is None:
            return
        dlg = SettingsDialog(self._window, on_apply=self._on_settings_apply,
                             on_theme=self.apply_theme)
        dlg.present()

    def _on_settings_apply(self) -> None:
        self._refresh_deck()
        self._target_monitor()
        if self._window is not None:
            self._window.set_chart_url(config_store.load_settings().get("chart_url", ""))

    def _target_monitor(self) -> None:
        """Move/fullscreen the window onto the configured (or auto-detected) Xeneon Edge."""
        if self._window is None:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        settings = config_store.load_settings()
        preferred = settings.get("target_monitor", "") or ""
        monitor = find_target_monitor(display, preferred)
        if monitor is None:
            print("[xeneon-edge] target monitor not found — staying on default display")
            return
        print(f"[xeneon-edge] targeting monitor {describe(monitor)}")
        if settings.get("fullscreen_on_target", True):
            self._window.fullscreen_on_monitor(monitor)
        else:
            # Best we can do without fullscreen on Wayland: ask compositor
            # (works on KDE), set size to match.
            g = monitor.get_geometry()
            self._window.set_default_size(g.width, g.height)


def main() -> int:
    app = XeneonEdgeApp()
    return app.run(sys.argv)
