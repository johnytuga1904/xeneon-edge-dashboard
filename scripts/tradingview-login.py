#!/usr/bin/env python3
"""Einmal-Login fuer die Chart-Module — in einem normalen Fenster.

Das Dashboard laeuft im Vollbild auf einem 2560x720-Streifen, an dem
ueblicherweise weder Tastatur noch Maus haengen. Dieses Skript oeffnet
dieselbe persistente WebKit-Session in einem gewoehnlichen Fenster auf dem
Hauptmonitor: hier anmelden, den gewuenschten gespeicherten Chart oeffnen,
"Als Chart uebernehmen" druecken — fertig. Cookies und LocalStorage liegen
danach in ~/.local/share/xeneon-edge/webkit/ und das Dashboard benutzt sie.

    ./scripts/tradingview-login.py                    # TradingView
    ./scripts/tradingview-login.py --site openmarket  # OpenMarket

Der Name ist historisch: das Skript kennt alle Seiten aus ``LOGIN_SITES`` in
ui/chart.py. Ohne Adresse startet es beim zuletzt uebernommenen Chart der
Seite (``chart_url`` bzw. ``openmarket_url`` in settings.json), sonst auf
deren Startseite.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

# Wie in run.sh: ohne das rendert WebKitGTK auf manchen Multi-GPU-Systemen nur
# eine schwarze Flaeche. Das Login-Fenster wird auch direkt aufgerufen, also
# nicht immer mit dem Environment aus run.sh.
if os.environ.get("XENEON_WEBKIT_DMABUF") != "1":
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Auf AMD+NVIDIA-Rechnern WebKit von der NVIDIA-EGL fernhalten — vor gi,
# weil GTK4 EGL schon beim Oeffnen des Bildschirms laedt.
from xeneon_edge import webkit_env  # noqa: E402
webkit_env.apply()

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from xeneon_edge import config_store  # noqa: E402
from xeneon_edge.ui import monitors  # noqa: E402
from xeneon_edge.ui.chart import LOGIN_SITES, import_webkit, make_session  # noqa: E402


class LoginWindow(Gtk.ApplicationWindow):
    def __init__(self, app, WebKit, session, url: str, site: dict):
        super().__init__(application=app,
                         title=f"{site['label']} — Login fuer das Chart-Panel")
        self.set_default_size(1400, 900)
        self._WebKit = WebKit
        self._site = site
        self._popups: list[Gtk.Window] = []

        # Bewusst *ohne* den Speicherdeckel des Chart-Panels: der Google-Login
        # oeffnet ein Popup im selben Web-Prozess, und Seite plus Popup lagen
        # bei 1,6 GB — mit Deckel wurde der Prozess nach 30 s gekillt, das
        # Fenster wurde leer und nahm keine Eingabe mehr an. Das Fenster lebt
        # nur Minuten, ein Deckel bringt hier nichts.
        self.view = WebKit.WebView(network_session=session)
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
        win = Gtk.Window(title=f"{self._site['label']} — Login",
                         transient_for=self, modal=False)
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
        settings[self._site["setting"]] = url
        config_store.save_settings(settings)
        print(f"{self._site['setting']} = {url}")
        print("Gespeichert. Der Editor traegt die Adresse ins Modul ein.")
        self.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Login-Fenster fuer die Chart-Module des Dashboards.")
    parser.add_argument("--site", choices=sorted(LOGIN_SITES), default="tradingview",
                        help="welche Seite (Standard: tradingview)")
    parser.add_argument("url", nargs="?", default="",
                        help="Startadresse; sonst der zuletzt uebernommene Chart")
    return parser.parse_args(argv)


def main() -> int:
    WebKit = import_webkit()
    if WebKit is None:
        print("WebKitGTK 6.0 fehlt — ohne das gibt es kein Chart-Panel.")
        print("  Fedora: sudo dnf install webkitgtk6.0")
        print("  Arch:   sudo pacman -S webkitgtk-6.0")
        print("  Debian: sudo apt install gir1.2-webkit-6.0")
        return 1

    args = parse_args(sys.argv[1:])
    site = LOGIN_SITES[args.site]
    url = args.url or (
        config_store.load_settings().get(site["setting"]) or site["start"])

    app = Gtk.Application(application_id="io.github.johnytuga1904.XeneonEdge.Login")
    session = make_session(WebKit)

    def on_activate(a):
        # Single-Instance: ein zweiter Start aktiviert diese Instanz. Dann das
        # vorhandene Fenster nach vorn holen statt ein zweites exakt darueber
        # zu legen — zwei identische Fenster uebereinander sehen aus wie eines,
        # das nicht reagiert.
        existing = a.get_active_window()
        if existing is not None:
            existing.present()
            return
        win = LoginWindow(a, WebKit, session, url, site)
        win.present()
        settings = config_store.load_settings()
        monitors.move_off_dashboard(
            win,
            str(settings.get("target_monitor", "") or ""),
            str(settings.get("launch_monitor", "") or ""))

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
