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
from gi.repository import Gtk, GLib  # noqa: E402

from ..paths import WEBKIT_DATA_DIR, WEBKIT_CACHE_DIR
from .. import theme as theme_mod
from .. import config_store

# Nach dem Ende des Web-Prozesses so lange warten, bevor die Seite neu
# geladen wird. Kurz genug, dass das Panel nicht minutenlang leer bleibt;
# lang genug, dass ein Prozess, der sofort wieder stirbt, keine Schleife
# ohne Pause dreht.
_RELOAD_DELAY_S = 3

_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<style>html,body{margin:0;background:__BG__;color:__FG__;font-family:sans-serif;height:100%;}</style>
</head><body>
<div class="tradingview-widget-container" style="height:100%;width:100%;">
  <div class="tradingview-widget-container__widget" style="height:100%;width:100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {
    "symbol": "BINANCE:BTCUSDT",
    "interval": "240",
    "timezone": "Europe/Zurich",
    "theme": "__MODE__",
    "style": "1",
    "autosize": true,
    "locale": "en",
    "backgroundColor": "__BG__",
    "gridColor": "__GRID__",
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


def widget_html(palette: theme_mod.Palette | None) -> str:
    """Das Widget-HTML in den Farben der Palette.

    Nur das anonyme Widget laesst sich faerben — die volle Chart-Seite bringt
    ihr eigenes Theme mit und folgt dem TradingView-Account.
    """
    p = palette or theme_mod.load(None)
    return (_HTML.replace("__BG__", p.bg)
                 .replace("__FG__", p.text)
                 .replace("__GRID__", theme_mod.rgba(p.text, 0.05))
                 .replace("__MODE__", "light" if p.is_light else "dark"))


def memory_limit_mb() -> int:
    try:
        return max(0, int(config_store.load_settings().get("web_memory_limit_mb", 0) or 0))
    except (TypeError, ValueError):
        return 0


def make_context(WebKit, limit_mb: int | None = None):
    """WebContext mit Speicherobergrenze fuer den Web-Prozess.

    Ohne Limit nimmt WebKit 3 GiB pro Prozess an und beendet nie von sich
    aus — die TradingView-Seite ist nach Stunden bei mehreren GB gesehen
    worden (3,7 GB Spitze der Unit). Mit Limit:

    * ab 70 % gibt WebKit Caches frei, ab 85 % auch aggressiv (GC);
    * bei 100 % wird der Web-Prozess beendet.

    Gemessen wird der volle RSS des Web-Prozesses (inklusive eingeblendeter
    Bibliotheken, rund 360 MB) — die Chart-Seite steht frisch geladen schon
    bei ~960 MB. Die Schwellen liegen deshalb hoch, sonst raeumt WebKit von
    der ersten Sekunde an dauernd auf. Die View meldet das per
      ``web-process-terminated``, und _try_webview laedt die Seite neu —
      ein paar Sekunden leeres Panel statt eines Prozesses ohne Deckel.

    ``limit_mb`` 0 heisst: WebKit-Defaults, kein Deckel.
    """
    if limit_mb is None:
        limit_mb = memory_limit_mb()
    if limit_mb <= 0:
        return WebKit.WebContext()
    settings = WebKit.MemoryPressureSettings.new()
    settings.set_memory_limit(limit_mb)
    # Reihenfolge zaehlt: WebKit prueft conservative < strict beim Setzen,
    # und strict steht vorher auf 0.5 — conservative 0.5 zuerst wuerde
    # abgewiesen (CRITICAL im Log, Wert bleibt 0.33).
    settings.set_strict_threshold(0.85)
    settings.set_conservative_threshold(0.7)
    settings.set_kill_threshold(1.0)
    settings.set_poll_interval(10.0)
    return WebKit.WebContext(memory_pressure_settings=settings)


def _watch_web_process(view, reload) -> None:
    """Seite neu laden, wenn der Web-Prozess weg ist.

    Ohne das bleibt das Panel nach einem Absturz oder dem Speicherlimit
    einfach leer — auf einem Geraet ohne Tastatur bis zum naechsten Neustart
    des Dashboards.
    """
    state = {"pending": None}

    def do_reload():
        state["pending"] = None
        try:
            reload()
        except Exception as e:
            print(f"[xeneon-edge] Chart-Reload fehlgeschlagen: {e}")
        return False

    def on_terminated(_view, reason):
        print(f"[xeneon-edge] Web-Prozess des Charts beendet ({reason.value_nick}) — "
              f"Neuladen in {_RELOAD_DELAY_S}s")
        if state["pending"] is None:
            state["pending"] = GLib.timeout_add_seconds(_RELOAD_DELAY_S, do_reload)

    view.connect("web-process-terminated", on_terminated)


def _try_webview(chart_url: str = "",
                 palette: theme_mod.Palette | None = None) -> Gtk.Widget | None:
    WebKit = import_webkit()
    if WebKit is None:
        return None
    try:
        context = make_context(WebKit)
        if chart_url:
            view = WebKit.WebView(web_context=context,
                                  network_session=make_session(WebKit))
            view.load_uri(chart_url)
            _watch_web_process(view, lambda: view.load_uri(chart_url))
        else:
            view = WebKit.WebView(web_context=context)
            html = widget_html(palette)
            view.load_html(html, "https://tradingview.com/")
            _watch_web_process(view, lambda: view.load_html(html, "https://tradingview.com/"))
        view.set_hexpand(True); view.set_vexpand(True)
        return view
    except Exception as e:
        print(f"[xeneon-edge] WebKit init failed: {e}")
        return None


def make_chart_widget(chart_url: str = "",
                      palette: theme_mod.Palette | None = None) -> Gtk.Widget:
    view = _try_webview(chart_url, palette)
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
