"""Adw.Application entry point."""
from __future__ import annotations
import os
import shutil
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Gio, Adw, GLib  # noqa: E402

from .paths import STYLE_CSS, ROOT
from . import theme as theme_mod
from .sensors import Aggregator
from .ui.window import MainWindow
from .ui.monitors import find_target_monitor, describe
from . import config_store, layout_store

# Der Omarchy-Symlink wird beim Theme-Wechsel mehrfach angefasst — buendeln.
_THEME_RELOAD_DELAY_MS = 300


class XeneonEdgeApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="ch.xeneon.edge")
        self._aggregator: Aggregator | None = None
        self._window: MainWindow | None = None
        # layout.json, settings.json, apps.json: der Editor schreibt sie, das
        # Dashboard hoert zu. Kein Rueckkanal noetig — und ein Texteditor
        # wirkt genauso.
        self._file_monitors: list[Gio.FileMonitor] = []
        self._reload_ids: dict[str, int] = {}
        self._settings_seen = config_store.load_settings()
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
        # aussieht (chart_url wandert ins TradingView-Modul).
        layout_store.migrate_from_settings(config_store.load_settings())

        self._window = MainWindow(self, on_open_settings=self._open_editor,
                                  palette=self._palette)
        self._refresh_deck()
        self._watch(layout_store.LAYOUT_FILE, "layout", self._reload_layout)
        self._watch(config_store.USER_SETTINGS_FILE, "settings", self._reload_settings)
        self._watch(config_store.USER_APPS_FILE, "apps", self._reload_apps)
        self._window.present()
        self._target_monitor()

        # Sensor aggregator pushes snapshots through GLib.idle_add to the UI
        def on_snapshot(snap):
            GLib.idle_add(self._window.apply_snapshot, snap)

        self._aggregator = Aggregator(on_snapshot=on_snapshot, interval=1.0,
                                      needs=self._window.needs)
        self._aggregator.set_feeds(self._window.feeds)
        self._aggregator.start()

    def do_shutdown(self):  # type: ignore[override]
        if self._aggregator is not None:
            self._aggregator.stop()
        for source_id in self._reload_ids.values():
            GLib.source_remove(source_id)
        for monitor in self._file_monitors:
            monitor.cancel()
        if self._theme_reload_id is not None:
            GLib.source_remove(self._theme_reload_id)
        if self._omarchy_monitor is not None:
            self._omarchy_monitor.cancel()
        Adw.Application.do_shutdown(self)

    # --------

    def _watch(self, path, key: str, reload) -> None:
        """Eine Konfigurationsdatei beobachten und bei Aenderung ``reload`` rufen.

        Auf die Datei zu horchen statt auf den Editor zu warten heisst: jeder
        Weg wirkt gleich — der Editor, ein Texteditor, ein Konfig-Werkzeug.

        Ein Speichervorgang meldet sich mehrfach (Temp-Datei + Umbenennen:
        CREATED, dann CHANGES_DONE_HINT); die Ereignisse werden pro Datei zu
        einem Reload gebuendelt, sonst flackert das Gitter.
        """
        try:
            gfile = Gio.File.new_for_path(str(path))
            monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        except Exception as e:
            print(f"[xeneon-edge] {path.name} wird nicht beobachtet: {e}")
            return

        def on_changed(_monitor, _f, _other, event_type):
            if event_type not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                                  Gio.FileMonitorEvent.MOVED_IN,
                                  Gio.FileMonitorEvent.CREATED):
                return
            pending = self._reload_ids.pop(key, None)
            if pending is not None:
                GLib.source_remove(pending)

            def fire():
                self._reload_ids.pop(key, None)
                reload()
                return False

            self._reload_ids[key] = GLib.timeout_add(250, fire)

        monitor.connect("changed", on_changed)
        self._file_monitors.append(monitor)

    def _reload_layout(self) -> None:
        if self._window is None:
            return
        print("[xeneon-edge] layout.json geaendert — Gitter wird neu gebaut")
        self._window.apply_layout(layout_store.load())
        if self._aggregator is not None:
            self._aggregator.set_needs(self._window.needs)
            self._aggregator.set_feeds(self._window.feeds)
        # Das Deck ist frisch gebaut und damit leer — oder wiederverwendet;
        # populate() ist in beiden Faellen richtig.
        self._refresh_deck()

    def _reload_settings(self) -> None:
        """settings.json geaendert (Editor): nur uebernehmen, was sich geaendert hat."""
        old = self._settings_seen
        new = config_store.load_settings()
        self._settings_seen = new
        print("[xeneon-edge] settings.json geaendert")
        if new.get("theme") != old.get("theme"):
            self.apply_theme(new.get("theme"))
        if any(new.get(k) != old.get(k)
               for k in ("deck_app_slots", "hold_to_confirm", "isolate_launches")):
            self._refresh_deck()
        if any(new.get(k) != old.get(k) for k in ("target_monitor", "fullscreen_on_target")):
            self._target_monitor()
        # web_memory_limit_mb wirkt auf neu gebaute Web-Views; ein laufender
        # Chart behaelt sein Limit bis zum naechsten Rebuild oder Neustart.

    def _reload_apps(self) -> None:
        print("[xeneon-edge] apps.json geaendert — Deck wird neu befuellt")
        self._refresh_deck()

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

    def _open_editor(self) -> None:
        """Das Zahnrad: den Editor auf dem Hauptmonitor starten.

        Der Editor ist der einzige Ort fuer Layout, Modul-Einstellungen, Deck
        und globale Settings. Er schreibt die drei JSON-Dateien, das Dashboard
        hoert per FileMonitor zu — hier muss nichts auf ihn gewartet werden.

        Eigene cgroup (systemd-run --scope): der WebKit-Stapel des Editors
        soll nicht in der Dashboard-Unit haengen, siehe launcher.py.
        """
        script = ROOT / "scripts" / "layout-editor.py"
        if not script.exists():
            print(f"[xeneon-edge] Editor fehlt: {script}")
            return
        argv = [sys.executable, str(script)]
        if shutil.which("systemd-run"):
            argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                    f"--unit=xeneon-editor-{os.getpid()}", "--"] + argv
        try:
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except GLib.Error as e:
            print(f"[xeneon-edge] Editor liess sich nicht starten: {e.message}")

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
