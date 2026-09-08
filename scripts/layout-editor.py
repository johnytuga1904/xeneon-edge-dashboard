#!/usr/bin/env python3
"""Layout-Editor — Module anordnen, in einem normalen Fenster.

Das Dashboard laeuft im Vollbild auf einem 2560x720-Streifen, an dem
ueblicherweise weder Tastatur noch Maus haengen. Dieses Skript oeffnet den
Editor deshalb auf dem Hauptmonitor — dasselbe Muster wie
scripts/tradingview-login.py.

    ./scripts/layout-editor.py

Gespeichert wird nach ~/.config/xeneon-edge/layout.json. Ein laufendes
Dashboard beobachtet die Datei und baut sein Gitter neu, ohne Neustart.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Wie in run.sh: ohne das rendert WebKitGTK auf manchen Multi-GPU-Systemen nur
# eine schwarze Flaeche. Der Editor wird direkt aufgerufen, hat also nicht das
# Environment aus run.sh.
if os.environ.get("XENEON_WEBKIT_DMABUF") != "1":
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

from xeneon_edge import config_store, editor, theme  # noqa: E402
from xeneon_edge.ui import monitors  # noqa: E402
from xeneon_edge.ui.chart import import_webkit  # noqa: E402

BRIDGE = "bridge"


def stage_geometry(display: Gdk.Display, preferred: str) -> dict:
    """Groesse des Zielmonitors — die Bezugsflaeche des Editors.

    Ohne erkannten Streifen bleibt es bei der Geometrie, fuer die das Dashboard
    entworfen ist: der Editor braucht *eine* Bezugsbreite, sonst kann er keine
    Proportionen zeichnen.
    """
    monitor = monitors.find_target_monitor(display, preferred)
    if monitor is None:
        return dict(editor.FALLBACK_STAGE)
    g = monitor.get_geometry()
    return {"width": g.width, "height": g.height,
            "connector": monitors._connector_name(monitor)}


class EditorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, WebKit, page: str):
        super().__init__(application=app, title="Xeneon Edge — Layout")
        self.set_default_size(1500, 950)

        ucm = WebKit.UserContentManager()
        # WebKit 6.0 will einen World-Namen, aeltere Bindings nicht.
        try:
            ucm.register_script_message_handler(BRIDGE, None)
        except TypeError:
            ucm.register_script_message_handler(BRIDGE)
        ucm.connect(f"script-message-received::{BRIDGE}", self._on_message)

        self.view = WebKit.WebView(user_content_manager=ucm)
        self.view.set_hexpand(True)
        self.view.set_vexpand(True)
        self.set_child(self.view)
        # Kein network_session: der Editor laedt nichts nach und soll sich
        # nicht in das Browserprofil des Chart-Panels einmischen.
        self.view.load_html(page, "xeneon-edge:editor")

    def _on_message(self, _ucm, js_value) -> None:
        try:
            raw = js_value.to_json(0)
        except Exception:
            raw = js_value.to_string()
        # postMessage schickt einen String, der als JSON-String ankommt —
        # also einmal auspacken, bevor das eigentliche Objekt dran ist.
        import json
        try:
            unwrapped = json.loads(raw)
            if isinstance(unwrapped, str):
                raw = unwrapped
        except (TypeError, ValueError):
            pass

        result = editor.handle_message(raw)
        print(("[xeneon-edge] " if result.ok else "[xeneon-edge] FEHLER: ") + result.message)
        self._reply(result.ok, result.message)

    def _reply(self, ok: bool, message: str) -> None:
        import json
        script = f"window.__saved({json.dumps(ok)}, {json.dumps(message)});"
        try:
            self.view.evaluate_javascript(script, -1, None, None, None, None, None)
        except Exception as e:
            print(f"[xeneon-edge] Rueckmeldung an die Seite fehlgeschlagen: {e}")


def main() -> int:
    WebKit = import_webkit()
    if WebKit is None:
        print("WebKitGTK 6.0 fehlt — ohne das gibt es keinen Layout-Editor.")
        print("  Fedora: sudo dnf install webkitgtk6.0")
        print("  Arch:   sudo pacman -S webkitgtk-6.0")
        print("  Debian: sudo apt install gir1.2-webkit-6.0")
        return 1

    settings = config_store.load_settings()
    app = Gtk.Application(application_id="ch.xeneon.edge.layout")

    def on_activate(a):
        display = Gdk.Display.get_default()
        stage = (stage_geometry(display, str(settings.get("target_monitor", "") or ""))
                 if display is not None else dict(editor.FALLBACK_STAGE))
        palette = theme.load(settings.get("theme"))
        page = editor.build_page(editor.payload(stage=stage, palette=palette))

        win = EditorWindow(a, WebKit, page)
        win.present()
        monitors.move_off_dashboard(win, str(settings.get("target_monitor", "") or ""))

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
