"""Adw.Application entry point."""
from __future__ import annotations
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Adw, GLib  # noqa: E402

from .paths import STYLE_CSS
from .sensors import Aggregator
from .ui.window import MainWindow
from .ui.settings import SettingsDialog
from .ui.monitors import find_target_monitor, describe
from . import config_store


class XeneonEdgeApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="ch.xeneon.edge")
        self._aggregator: Aggregator | None = None
        self._window: MainWindow | None = None

    def do_startup(self):  # type: ignore[override]
        Adw.Application.do_startup(self)
        # force dark color scheme for libadwaita widgets
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self._load_css()

    def do_activate(self):  # type: ignore[override]
        if self._window is not None:
            self._window.present()
            return
        self._window = MainWindow(self, on_open_settings=self._open_settings)
        self._refresh_deck()
        self._window.present()
        self._target_monitor()

        # Sensor aggregator pushes snapshots through GLib.idle_add to the UI
        def on_snapshot(snap):
            GLib.idle_add(self._window.apply_snapshot, snap)

        self._aggregator = Aggregator(on_snapshot=on_snapshot, interval=1.0)
        self._aggregator.start()

    def do_shutdown(self):  # type: ignore[override]
        if self._aggregator is not None:
            self._aggregator.stop()
        Adw.Application.do_shutdown(self)

    # --------

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(str(STYLE_CSS))
        except Exception as e:
            print(f"[xeneon-edge] CSS load failed: {e}")
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

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
        dlg = SettingsDialog(self._window, on_apply=self._on_settings_apply)
        dlg.present()

    def _on_settings_apply(self) -> None:
        self._refresh_deck()
        self._target_monitor()

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
