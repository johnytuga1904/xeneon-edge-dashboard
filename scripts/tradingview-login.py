#!/usr/bin/env python3
"""Einmal-Login fuer das Chart-Panel — in einem normalen Fenster.

Das Dashboard laeuft im Vollbild auf einem 2560x720-Streifen, an dem
ueblicherweise weder Tastatur noch Maus haengen. Dieses Skript oeffnet
dieselbe persistente WebKit-Session in einem gewoehnlichen Fenster auf dem
Hauptmonitor: hier anmelden, den gewuenschten gespeicherten Chart oeffnen,
"Als Chart uebernehmen" druecken — fertig. Cookies und LocalStorage liegen
danach in ~/.local/share/xeneon-edge/webkit/ und das Dashboard benutzt sie.

    ./scripts/tradingview-login.py

Ohne Argument startet es bei der aktuell konfigurierten chart_url, sonst bei
https://www.tradingview.com/chart/.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Wie in run.sh: ohne das rendert WebKitGTK auf manchen Multi-GPU-Systemen nur
# eine schwarze Flaeche. Das Login-Fenster wird auch direkt aufgerufen, also
# nicht immer mit dem Environment aus run.sh.
if os.environ.get("XENEON_WEBKIT_DMABUF") != "1":
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from xeneon_edge import config_store  # noqa: E402
from xeneon_edge.ui import monitors  # noqa: E402
from xeneon_edge.ui.chart import import_webkit, make_session, make_context  # noqa: E402

START_URL = "https://www.tradingview.com/chart/"


class LoginWindow(Gtk.ApplicationWindow):
    def __init__(self, app, WebKit, session, url: str):
        super().__init__(application=app, title="TradingView — Login fuer das Chart-Panel")
        self.set_default_size(1400, 900)
        self._WebKit = WebKit
        self._popups: list[Gtk.Window] = []

        # Dasselbe Speicherlimit wie das Panel — die Seite ist dieselbe.
        self.view = WebKit.WebView(web_context=make_context(WebKit),
                                   network_session=session)
        self.view.set_hexpand(True)
        self.view.set_vexpand(True)
        self.view.connect("notify::uri", self._on_uri)
        self.view.connect("create", self._on_create)

        header = Gtk.HeaderBar()
        self.url_label = Gtk.Label(label=url)
        self.url_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.url_label.add_css_class("dim-label")
        header.set_title_widget(self.url_label)

        save = Gtk.Button(label="Als Chart uebernehmen")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save)
        header.pack_end(save)
        self.set_titlebar(header)

        self.set_child(self.view)
        self.view.load_uri(url)

    def _on_uri(self, view, _param):
        self.url_label.set_label(view.get_uri() or "")

    def _on_create(self, view, navigation_action):
        """Login ueber Google/Apple oeffnet ein Popup — ohne diesen Handler
        passiert beim Klick schlicht nichts.

        Die zurueckgegebene View MUSS ueber related_view mit der Opener-View
        verwandt sein; die API-Doku des create-Signals verlangt das. Eine
        unverwandte View (network_session= statt related_view=) laeuft in
        WebKit auf ein leeres std::optional<WebCore::WindowFeatures>, und weil
        Arch libstdc++ mit _GLIBCXX_ASSERTIONS baut, endet das im Abort:

          optional:1244: std::optional<WebCore::WindowFeatures>::operator*():
          Assertion 'this->_M_is_engaged()' failed.

        related_view vererbt Web-Prozess *und* Netzwerk-Session, das Popup
        schreibt seine Cookies also weiterhin in dieselbe Session — ein
        eigenes network_session= waere ohnehin falsch gewesen.
        """
        popup_view = self._WebKit.WebView(related_view=view)
        win = Gtk.Window(title="TradingView — Login", transient_for=self, modal=False)
        win.set_default_size(560, 720)
        win.set_child(popup_view)
        popup_view.connect("ready-to-show", lambda _v: win.present())
        popup_view.connect("close", lambda _v: win.close())
        self._popups.append(win)
        return popup_view

    def _on_save(self, _btn):
        url = self.view.get_uri() or ""
        if "/chart/" not in url:
            self.url_label.set_label("Das ist keine /chart/-URL — erst den Chart oeffnen.")
            return
        settings = config_store.load_settings()
        settings["chart_url"] = url
        config_store.save_settings(settings)
        print(f"chart_url = {url}")
        print("Gespeichert. Das Dashboard uebernimmt es beim naechsten Start.")
        self.close()


def main() -> int:
    WebKit = import_webkit()
    if WebKit is None:
        print("WebKitGTK 6.0 fehlt — ohne das gibt es kein Chart-Panel.")
        print("  Fedora: sudo dnf install webkitgtk6.0")
        print("  Arch:   sudo pacman -S webkitgtk-6.0")
        print("  Debian: sudo apt install gir1.2-webkit-6.0")
        return 1

    url = sys.argv[1] if len(sys.argv) > 1 else (
        config_store.load_settings().get("chart_url") or START_URL)

    app = Gtk.Application(application_id="ch.xeneon.edge.login")
    session = make_session(WebKit)

    def on_activate(a):
        win = LoginWindow(a, WebKit, session, url)
        win.present()
        monitors.move_off_dashboard(
        win, str(config_store.load_settings().get("target_monitor", "") or ""))

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
