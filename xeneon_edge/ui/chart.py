"""WebKitGTK-Views: das TradingView-Modul und das freie Web-Panel.

Beide zeigen eine Seite in einer ``WebKit.WebView``; getrennt sind sie, weil
sie verschiedene Fragen stellen. Das Web-Panel fragt nur nach einer Adresse.
TradingView fragt, *wie*:

* **Widget** — das eingebettete *Advanced Chart*. Kein Login, kein Account;
  Symbol, Intervall, Zeitzone und Indikatoren kommen aus der Modul-Konfiguration
  und werden unten in die Seite geschrieben.
* **Eigener Chart** — eine URL wie ``https://www.tradingview.com/chart/AbCdEf12/``:
  die echte Chart-Seite mit der gespeicherten Browser-Session, also mit dem
  Layout aus dem eigenen Account. Das Widget kann das nicht, es ist account-los
  und kennt keine gespeicherten Layouts.

Fuer die zweite Variante braucht es eine *persistente* ``NetworkSession``.
Ohne eigenes Datenverzeichnis liegt der Cookie-Jar im Speicher und der Login
ist nach jedem Neustart weg. Angemeldet wird einmalig ueber
``scripts/tradingview-login.py`` — dasselbe Profil, aber in einem normalen
Fenster auf dem Hauptmonitor, wo Tastatur und Maus sind.

Ohne WebKitGTK faellt beides auf einen Platzhalter mit Installationshinweis
zurueck.
"""
from __future__ import annotations
import json
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
  __CONFIG__
  </script>
</div>
</body></html>"""

# Voreinstellung des Widgets, wenn das Modul nichts anderes sagt. Bis Schritt 6
# stand das alles fest im HTML.
TV_DEFAULTS = {
    "symbol": "BINANCE:BTCUSDT",
    "interval": "240",
    "timezone": "Europe/Zurich",
    "toolbars": True,
    "studies": ["STD;Divergence%1Indicator"],
}

# Was das Intervall-Auswahlfeld anbietet. Die Werte sind die des Widgets:
# Minuten als Zahl, darueber D/W/M.
TV_INTERVALS = (
    ("1", "1 Minute"), ("5", "5 Minuten"), ("15", "15 Minuten"),
    ("30", "30 Minuten"), ("60", "1 Stunde"), ("240", "4 Stunden"),
    ("D", "1 Tag"), ("W", "1 Woche"), ("M", "1 Monat"),
)

# Indikatoren zum Anklicken. Die Kennungen sind die der TradingView-Bibliothek
# ("%1" steht fuer ein Leerzeichen); "volume" ist keine davon, sondern schaltet
# das eingebaute Volumen unter dem Chart ein — deshalb die Sonderbehandlung in
# widget_config().
#
# Jede Kennung hier ist nachgemessen: die Seite wurde in WebKit geladen und in
# der Legende nachgesehen, was tatsaechlich erscheint. Das ist noetig, weil das
# Widget eine unbekannte Kennung *stumm* verwirft — es gibt keine Fehlermeldung,
# der Indikator fehlt einfach. Nicht erkannt wurden unter anderem ATR, OBV, ADX,
# MFI und Awesome Oscillator; sie fehlen deshalb in der Liste, statt eine
# Auswahl anzubieten, die nichts tut.
TV_VOLUME = "volume"
TV_STUDIES = (
    (TV_VOLUME, "Volumen"),
    ("STD;RSI", "RSI"),
    ("STD;MACD", "MACD"),
    ("STD;Bollinger_Bands", "Bollinger-Baender"),
    ("STD;EMA", "EMA (gleitender Durchschnitt)"),
    ("STD;SMA", "SMA (gleitender Durchschnitt)"),
    ("STD;VWAP", "VWAP"),
    ("STD;Stochastic_RSI", "Stochastic RSI"),
    ("STD;Ichimoku%1Cloud", "Ichimoku-Wolke"),
    ("STD;Supertrend", "Supertrend"),
    ("STD;Divergence%1Indicator", "RSI-Divergenz"),
)

# Das kostenlose Widget nimmt fuenf Indikatoren an; alles darueber laesst es
# stillschweigend weg — und zwar die *letzten* der Liste. Lieber hier kappen
# und es im Editor dazuschreiben, als den Nutzer raten lassen, warum sein
# sechster Haken nichts bewirkt. Volumen zaehlt nicht mit, es ist eine eigene
# Option des Widgets.
TV_MAX_STUDIES = 5


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
    # 0700: in cookies.sqlite liegt die TradingView-Session. Bestehende
    # Verzeichnisse werden nachgezogen, mkdir allein laesst sie unveraendert.
    for d in (WEBKIT_DATA_DIR, WEBKIT_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            d.chmod(0o700)
        except OSError:
            pass
    session = WebKit.NetworkSession.new(str(WEBKIT_DATA_DIR), str(WEBKIT_CACHE_DIR))
    session.get_cookie_manager().set_persistent_storage(
        str(WEBKIT_DATA_DIR / "cookies.sqlite"), WebKit.CookiePersistentStorage.SQLITE
    )
    return session


def widget_config(config: dict | None = None) -> dict:
    """Die Widget-Optionen aus der Modul-Konfiguration.

    Alles, was nicht gesetzt ist, faellt auf TV_DEFAULTS zurueck — ein frisch
    hinzugefuegtes Modul zeigt damit denselben Chart wie frueher das fest
    verdrahtete HTML.
    """
    cfg = config or {}
    raw = cfg.get("studies")
    chosen = list(raw) if isinstance(raw, list) else list(TV_DEFAULTS["studies"])
    known = {value for value, _label in TV_STUDIES}
    studies = [s for s in chosen if s in known and s != TV_VOLUME][:TV_MAX_STUDIES]
    toolbars = cfg.get("toolbars", TV_DEFAULTS["toolbars"]) is not False
    return {
        "symbol": str(cfg.get("symbol") or TV_DEFAULTS["symbol"]),
        "interval": str(cfg.get("interval") or TV_DEFAULTS["interval"]),
        "timezone": str(cfg.get("timezone") or TV_DEFAULTS["timezone"]),
        "style": "1",
        "autosize": True,
        "locale": "en",
        "hide_top_toolbar": not toolbars,
        "hide_side_toolbar": not toolbars,
        "allow_symbol_change": True,
        "withdateranges": True,
        "hide_volume": TV_VOLUME not in chosen,
        "save_image": False,
        "calendar": False,
        "studies": studies,
    }


def widget_html(palette: theme_mod.Palette | None, config: dict | None = None) -> str:
    """Das Widget-HTML in den Farben der Palette.

    Nur das anonyme Widget laesst sich faerben — die volle Chart-Seite bringt
    ihr eigenes Theme mit und folgt dem TradingView-Account.
    """
    p = palette or theme_mod.load(None)
    options = widget_config(config)
    options["theme"] = "light" if p.is_light else "dark"
    options["backgroundColor"] = p.bg
    options["gridColor"] = theme_mod.rgba(p.text, 0.05)
    return (_HTML.replace("__CONFIG__", json.dumps(options, indent=2))
                 .replace("__BG__", p.bg)
                 .replace("__FG__", p.text))


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


def _log_page_loads(view, what: str) -> None:
    """Jedes Laden der Seite ins Journal schreiben.

    Eine Seite, die sich von selbst neu laedt, sieht auf dem Streifen aus wie
    ein Flackern des Dashboards — und ohne diese Zeile ist von aussen nicht zu
    unterscheiden, ob das Dashboard neu baut oder die Seite neu laedt. Der
    erste Aufbau schreibt eine Zeile, jede weitere ist ein Neuladen.
    """
    state = {"loads": 0}

    def on_load(_view, event) -> None:
        WebKit = import_webkit()
        if WebKit is None or event != WebKit.LoadEvent.STARTED:
            return
        state["loads"] += 1
        kind = "erster Aufbau" if state["loads"] == 1 else f"Neuladen #{state['loads'] - 1}"
        print(f"[xeneon-edge] {what}: {kind}")

    view.connect("load-changed", on_load)


def _try_webview(url: str = "", html: str = "", base: str = "") -> Gtk.Widget | None:
    """View auf ``url``, oder auf ``html`` mit ``base`` als Herkunft.

    Eine Adresse bekommt die persistente Session: sonst waere jeder Login —
    TradingView wie Webmail — nach einem Neustart des Dashboards weg. Das
    eingebettete Widget braucht sie nicht, es meldet sich nirgends an.
    """
    WebKit = import_webkit()
    if WebKit is None:
        return None
    try:
        context = make_context(WebKit)
        if url:
            view = WebKit.WebView(web_context=context,
                                  network_session=make_session(WebKit))
            _log_page_loads(view, f"Seite {url[:60]}")
            view.load_uri(url)
            _watch_web_process(view, lambda: view.load_uri(url))
        else:
            view = WebKit.WebView(web_context=context)
            _log_page_loads(view, "TradingView-Widget")
            view.load_html(html, base)
            _watch_web_process(view, lambda: view.load_html(html, base))
        view.set_hexpand(True); view.set_vexpand(True)
        return view
    except Exception as e:
        print(f"[xeneon-edge] WebKit init failed: {e}")
        return None


def _wrap(view: Gtk.Widget) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("panel")
    box.append(view)
    return box


def _placeholder(title: str, message: str) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class("panel")
    box.set_vexpand(True); box.set_hexpand(True)
    label = Gtk.Label(label=title, xalign=0)
    label.add_css_class("panel-label")
    box.append(label)
    msg = Gtk.Label(label=message, xalign=0)
    msg.add_css_class("muted")
    msg.set_wrap(True)
    box.append(msg)
    return box


NO_WEBKIT = ("Braucht WebKitGTK 6.0.\nInstalliere mit:\n\n"
             "  Fedora: sudo dnf install webkitgtk6.0\n"
             "  Arch:   sudo pacman -S webkitgtk-6.0\n"
             "  Debian: sudo apt install gir1.2-webkit-6.0")


def make_tradingview_widget(config: dict | None = None,
                            palette: theme_mod.Palette | None = None) -> Gtk.Widget:
    """TradingView — eigener Chart aus dem Account oder eingebettetes Widget."""
    cfg = config or {}
    url = str(cfg.get("url") or "") if str(cfg.get("mode") or "widget") == "account" else ""
    if url:
        view = _try_webview(url=url)
    else:
        html = widget_html(palette, cfg)
        view = _try_webview(html=html, base="https://tradingview.com/")
    if view is not None:
        return _wrap(view)
    return _placeholder("TRADINGVIEW", NO_WEBKIT)


def make_web_widget(url: str = "") -> Gtk.Widget:
    """Freies Web-Panel: eine Adresse, sonst nichts."""
    if not url:
        return _placeholder(
            "WEB-PANEL",
            "Keine Adresse eingestellt. Im Editor das Modul anklicken und "
            "unter \u201eAdresse\u201c eine URL eintragen — oder das "
            "TradingView-Modul nehmen, wenn es um Charts geht.")
    view = _try_webview(url=url)
    return _wrap(view) if view is not None else _placeholder("WEB-PANEL", NO_WEBKIT)
