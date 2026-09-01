"""Chart-Panel: TradingView in einer WebKitGTK-View. Faellt auf einen
Platzhalter zurueck, wenn WebKitGTK fehlt.

Zwei Betriebsarten, gesteuert ueber ``chart_url`` in den Settings:

* leer (Default) — das eingebettete *Advanced Chart*-Widget. Kein Login, kein
  Account, Symbol und Indikatoren stehen fest im HTML unten.
* eine URL wie ``https://www.tradingview.com/chart/AbCdEf12/`` — die echte
  Chart-Seite mit der gespeicherten Browser-Session, also mit dem Layout aus
  dem eigenen Account. Das Widget kann das nicht: es ist account-los und kennt
  keine gespeicherten Layouts.

Fuer die zweite Variante braucht es eine *persistente* ``NetworkSession``.
Ohne eigenes Datenverzeichnis liegt der Cookie-Jar im Speicher und der Login
ist nach jedem Neustart weg. Angemeldet wird einmalig ueber
``scripts/tradingview-login.py`` — dasselbe Profil, aber in einem normalen
Fenster auf dem Hauptmonitor, wo Tastatur und Maus sind.
"""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..paths import WEBKIT_DATA_DIR, WEBKIT_CACHE_DIR

_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<style>html,body{margin:0;background:#000;color:#fff;font-family:sans-serif;height:100%;}</style>
</head><body>
<div class="tradingview-widget-container" style="height:100%;width:100%;">
  <div class="tradingview-widget-container__widget" style="height:100%;width:100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {
    "symbol": "BINANCE:BTCUSDT",
    "interval": "240",
    "timezone": "Europe/Zurich",
    "theme": "dark",
    "style": "1",
    "autosize": true,
    "locale": "en",
    "backgroundColor": "rgba(0,0,0,1)",
    "gridColor": "rgba(255,255,255,0.05)",
    "hide_top_toolbar": false,
    "hide_side_toolbar": false,
    "allow_symbol_change": true,
    "withdateranges": true,
    "hide_volume": true,
    "save_image": false,
    "calendar": false,
    "studies": ["STD;Divergence%1Indicator"]
  }
  </script>
</div>
</body></html>"""


def import_webkit():
    """WebKit 6.0 (GTK4), sonst None. WebKit2 5.0 ist GTK3 und passt nicht."""
    try:
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # type: ignore
        return WebKit
    except Exception:
        return None


def make_session(WebKit):
    """Persistente Session: Cookies und LocalStorage ueberleben den Neustart.

    Ohne das waere der TradingView-Login bei jedem Start des Dashboards weg.
    Wird von scripts/tradingview-login.py mitbenutzt — beide muessen exakt
    dieselben Verzeichnisse nehmen, sonst teilen sie den Login nicht.
    """
    WEBKIT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEBKIT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    session = WebKit.NetworkSession.new(str(WEBKIT_DATA_DIR), str(WEBKIT_CACHE_DIR))
    session.get_cookie_manager().set_persistent_storage(
        str(WEBKIT_DATA_DIR / "cookies.sqlite"), WebKit.CookiePersistentStorage.SQLITE
    )
    return session


def _try_webview(chart_url: str = "") -> Gtk.Widget | None:
    WebKit = import_webkit()
    if WebKit is None:
        return None
    try:
        if chart_url:
            view = WebKit.WebView(network_session=make_session(WebKit))
            view.load_uri(chart_url)
        else:
            view = WebKit.WebView()
            view.load_html(_HTML, "https://tradingview.com/")
        view.set_hexpand(True); view.set_vexpand(True)
        return view
    except Exception as e:
        print(f"[xeneon-edge] WebKit init failed: {e}")
        return None


def make_chart_widget(chart_url: str = "") -> Gtk.Widget:
    view = _try_webview(chart_url)
    if view is not None:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add_css_class("panel")
        wrap.append(view)
        return wrap
    # fallback placeholder
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class("panel")
    box.set_vexpand(True); box.set_hexpand(True)
    title = Gtk.Label(label="BTC/USDT", xalign=0)
    title.add_css_class("panel-label")
    box.append(title)
    msg = Gtk.Label(
        label="Chart-Widget braucht WebKitGTK 6.0.\nInstalliere mit:\n\n"
              "  Fedora: sudo dnf install webkitgtk6.0\n"
              "  Arch:   sudo pacman -S webkitgtk-6.0\n"
              "  Debian: sudo apt install gir1.2-webkit-6.0",
        xalign=0)
    msg.add_css_class("muted")
    msg.set_wrap(True)
    box.append(msg)
    return box
