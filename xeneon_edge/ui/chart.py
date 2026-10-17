"""WebKitGTK-Views: TradingView, OpenMarket und das freie Web-Panel.

Alle zeigen eine Seite in einer ``WebKit.WebView``; getrennt sind sie, weil
sie verschiedene Fragen stellen. Das Web-Panel fragt nur nach einer Adresse.
OpenMarket fragt nach *dem eigenen Chart* aus dem Account (eine Adresse wie
``https://openmarket.xyz/chart/AbCdEf12``, die das Login-Fenster eintraegt).
TradingView fragt, *wie*:

* **Widget** — das eingebettete *Advanced Chart*. Kein Login, kein Account;
  Symbol, Intervall, Zeitzone und Indikatoren kommen aus der Modul-Konfiguration
  und werden unten in die Seite geschrieben.
* **Eigener Chart** — eine URL wie ``https://www.tradingview.com/chart/AbCdEf12/``:
  die echte Chart-Seite mit der gespeicherten Browser-Session, also mit dem
  Layout aus dem eigenen Account. Das Widget kann das nicht, es ist account-los
  und kennt keine gespeicherten Layouts.

Fuer die zweite Variante und fuer OpenMarket braucht es eine *persistente*
``NetworkSession``. Ohne eigenes Datenverzeichnis liegt der Cookie-Jar im
Speicher und der Login ist nach jedem Neustart weg. Angemeldet wird einmalig
ueber ``scripts/tradingview-login.py`` (mit ``--site openmarket`` fuer
OpenMarket) — dasselbe Profil, aber in einem normalen Fenster auf dem
Hauptmonitor, wo Tastatur und Maus sind. Welche Seiten das Fenster kennt,
steht in ``LOGIN_SITES``.

Ohne WebKitGTK faellt beides auf einen Platzhalter mit Installationshinweis
zurueck.
"""
from __future__ import annotations
import json
import os
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio  # noqa: E402

from ..paths import WEBKIT_DATA_DIR, WEBKIT_CACHE_DIR
from .. import theme as theme_mod
from .. import config_store

# Nach dem Ende des Web-Prozesses so lange warten, bevor die Seite neu
# geladen wird. Kurz genug, dass das Panel nicht minutenlang leer bleibt;
# lang genug, dass ein Prozess, der sofort wieder stirbt, keine Schleife
# ohne Pause dreht.
_RELOAD_DELAY_S = 3

# So lange darf ein Laden ohne ersten Inhalt (COMMITTED) dauern, bevor es
# abgebrochen und neu angestossen wird. Ein gesundes Laden der Chart-Seite
# committed nach wenigen Sekunden; was nach 45 s noch nichts hat, haengt —
# gesehen am 13.09.2026: ein Neuladen wollte ueber eine TCP-Verbindung
# senden, die seit dem VPN-Start stumm tot war (kein RST, nur Retransmits
# mit 120 s RTO). Der Kernel gibt so ein Socket erst nach ~20 min auf, und
# so lange stand das alte Bild, WebProcess idle. stop_loading() gibt die
# Verbindung frei; der neue Versuch oeffnet eine frische.
_LOAD_TIMEOUT_S = 45

# Nach einem Netzwechsel (VPN hoch oder runter, WLAN gewechselt) so lange
# Ruhe abwarten, bevor die Seite neu geladen wird. NetworkManager meldet
# einen Wechsel meist in mehreren Schritten hintereinander; ein Reload
# pro Schritt waere Flackern ohne Nutzen.
_NETWORK_SETTLE_S = 5

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

def system_timezone() -> str:
    """IANA-Name der Systemzeitzone (/etc/localtime), sonst Etc/UTC.

    Das Widget will einen IANA-Namen; TZ aus der Umgebung ist meist leer, und
    ein fest eingetragener Ort waere auf jedem anderen Rechner falsch.
    """
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz:
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return "Etc/UTC"
    _, sep, name = target.partition("/zoneinfo/")
    return name if sep and name else "Etc/UTC"


# Voreinstellung des Widgets, wenn das Modul nichts anderes sagt. Bis Schritt 6
# stand das alles fest im HTML.
TV_DEFAULTS = {
    "symbol": "BINANCE:BTCUSDT",
    "interval": "240",
    "timezone": system_timezone(),
    "toolbars": True,
    "studies": ["STD;Divergence%1Indicator"],
}

# Was das Intervall-Auswahlfeld anbietet. Die Werte sind die des Widgets:
# Minuten als Zahl, darueber D/W/M.
TV_INTERVALS = (
    ("1", "1 minute"), ("5", "5 minutes"), ("15", "15 minutes"),
    ("30", "30 minutes"), ("60", "1 hour"), ("240", "4 hours"),
    ("D", "1 day"), ("W", "1 week"), ("M", "1 month"),
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
    (TV_VOLUME, "Volume"),
    ("STD;RSI", "RSI"),
    ("STD;MACD", "MACD"),
    ("STD;Bollinger_Bands", "Bollinger Bands"),
    ("STD;EMA", "EMA (moving average)"),
    ("STD;SMA", "SMA (moving average)"),
    ("STD;VWAP", "VWAP"),
    ("STD;Stochastic_RSI", "Stochastic RSI"),
    ("STD;Ichimoku%1Cloud", "Ichimoku Cloud"),
    ("STD;Supertrend", "Supertrend"),
    ("STD;Divergence%1Indicator", "RSI divergence"),
)

# Seiten, fuer die das Login-Fenster (scripts/tradingview-login.py) einen
# Chart waehlen kann. ``start`` ist die Adresse, bei der das Fenster ohne
# gespeicherten Chart aufgeht; ``setting`` der Schluessel in settings.json,
# in den "Als Chart uebernehmen" die Adresse schreibt und aus dem der Editor
# sie danach ins Modul traegt. Beide Seiten fuehren ihre Charts unter
# ``/chart/<id>`` — darauf prueft das Fenster, bevor es speichert.
LOGIN_SITES = {
    "tradingview": {
        "label": "TradingView",
        "start": "https://www.tradingview.com/chart/",
        "setting": "chart_url",
    },
    "openmarket": {
        "label": "OpenMarket",
        "start": "https://openmarket.xyz/",
        "setting": "openmarket_url",
    },
}

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


def _safe_reload(reload, view, what: str) -> None:
    try:
        reload(view)
    except Exception as e:
        print(f"[xeneon-edge] {what}: reload failed: {e}")


def _watch_web_process(view, reload, what: str) -> None:
    """Seite neu laden, wenn der Web-Prozess weg ist.

    Ohne das bleibt das Panel nach einem Absturz oder dem Speicherlimit
    einfach leer — auf einem Geraet ohne Tastatur bis zum naechsten Neustart
    des Dashboards.
    """
    state = {"pending": None}

    def on_terminated(_view, reason):
        print(f"[xeneon-edge] {what}: web process ended ({reason.value_nick}) — "
              f"reloading in {_RELOAD_DELAY_S}s")

        def do_reload():
            state["pending"] = None
            _safe_reload(reload, _view, what)
            return False

        if state["pending"] is None:
            state["pending"] = GLib.timeout_add_seconds(_RELOAD_DELAY_S, do_reload)

    view.connect("web-process-terminated", on_terminated)


def _watch_page_loads(view, reload, what: str, home: str):
    """Jedes Laden ins Journal schreiben — und ein haengendes abbrechen.

    Eine Seite, die sich von selbst neu laedt, sieht auf dem Streifen aus wie
    ein Flackern des Dashboards — und ohne diese Zeilen ist von aussen nicht
    zu unterscheiden, ob das Dashboard neu baut oder die Seite neu laedt. Der
    erste Aufbau schreibt eine Zeile, jede weitere ist ein Neuladen; dazu
    kommt, wann es fertig war, und wohin die Seite dabei navigiert ist, falls
    nicht an ``home`` — die Adresse, die das Modul eigentlich zeigen soll.

    Der Waechter: kommt nach STARTED innerhalb von _LOAD_TIMEOUT_S kein
    COMMITTED, wird das Laden abgebrochen und neu angestossen. Bis dahin
    zeigt WebKit das alte Bild — auf dem Streifen sieht das aus, als haenge
    der Chart, und ohne Tastatur kommt man da nicht mehr raus.

    Gibt eine Funktion zurueck, die den laufenden Waechter abbestellt.
    """
    state = {"loads": 0, "timer": None, "started": None, "cancelled": False}
    # TradingView schreibt seine Query-Parameter um; nur Host und Pfad zaehlen.
    home_path = home.split("?", 1)[0].split("#", 1)[0]

    def cancel_timer() -> None:
        if state["timer"] is not None:
            GLib.source_remove(state["timer"])
            state["timer"] = None

    def on_timeout(v):
        state["timer"] = None
        print(f"[xeneon-edge] {what}: no content after {_LOAD_TIMEOUT_S}s "
              f"({v.get_uri() or '?'}) — load cancelled, retrying")
        try:
            v.stop_loading()
        except Exception as e:
            print(f"[xeneon-edge] {what}: stop_loading failed: {e}")
        _safe_reload(reload, v, what)
        return False

    def on_load(v, event) -> None:
        WebKit = import_webkit()
        if WebKit is None:
            return
        if event == WebKit.LoadEvent.STARTED:
            state["loads"] += 1
            state["started"] = GLib.get_monotonic_time()
            kind = "first load" if state["loads"] == 1 else f"reload #{state['loads'] - 1}"
            print(f"[xeneon-edge] {what}: {kind}")
            cancel_timer()
            state["timer"] = GLib.timeout_add_seconds(_LOAD_TIMEOUT_S, on_timeout, v)
        elif event == WebKit.LoadEvent.COMMITTED:
            cancel_timer()
        elif event == WebKit.LoadEvent.FINISHED:
            cancel_timer()
            if state["cancelled"]:
                # Das FINISHED eines abgebrochenen Ladens; die Meldung dazu
                # stand schon beim Abbruch im Journal.
                state["cancelled"] = False
                return
            secs = ""
            if state["started"] is not None:
                secs = f" after {(GLib.get_monotonic_time() - state['started']) / 1e6:.1f}s"
            uri = v.get_uri() or ""
            where = "" if uri.startswith(home_path) else f" — now at {uri[:80]}"
            print(f"[xeneon-edge] {what}: done{secs}{where}")

    def on_failed(v, _event, failing_uri, error) -> bool:
        # Reihenfolge nach stop_loading(), nachgemessen mit WebKitGTK 2.52:
        # load-failed (cancelled) und FINISHED des alten Ladens kommen erst,
        # dann STARTED des neuen — der Waechter des neuen bleibt also stehen.
        cancel_timer()
        WebKit = import_webkit()
        if WebKit is not None and error.matches(WebKit.network_error_quark(),
                                                WebKit.NetworkError.CANCELLED):
            state["cancelled"] = True
            return False
        print(f"[xeneon-edge] {what}: load failed ({failing_uri[:80]}): "
              f"{error.message}")
        return False  # WebKit zeigt seine Fehlerseite; der naechste Reload raeumt auf

    view.connect("load-changed", on_load)
    view.connect("load-failed", on_failed)
    return cancel_timer


def _reload_on_network_change(view, reload, what: str):
    """Nach einem Netzwechsel die Seite einmal neu laden.

    Dashboard und VPN starten beim Login in derselben Sekunde. Verbindungen,
    die WebKit noch ueber das LAN aufgebaut hat, bevor der Tunnel stand, sind
    danach stumm tot: kein RST, nur nie wieder ein Byte. Die Seite merkt das
    erst, wenn sie darauf senden will — Stunden spaeter, und dann haengt sie
    (siehe _LOAD_TIMEOUT_S). Ein Reload nach dem Wechsel oeffnet alle
    Verbindungen frisch ueber den neuen Weg.

    Der NetworkMonitor lebt laenger als die View, und sein Handler haelt sie
    fest — samt Web-Prozess. Gibt deshalb eine Funktion zurueck, die den
    Handler abhaengt; _WebPanel.teardown ruft sie, wenn das Modul aus dem
    Layout faellt. (Eine schwache Referenz taugt nicht: PyGObject haelt den
    Python-Wrapper einer View nicht am Leben, solange nur GTK sie haelt.)
    """
    monitor = Gio.NetworkMonitor.get_default()
    state = {"pending": None, "handler": None}

    def detach() -> None:
        if state["pending"] is not None:
            GLib.source_remove(state["pending"])
            state["pending"] = None
        if state["handler"] is not None:
            monitor.disconnect(state["handler"])
            state["handler"] = None

    def fire():
        state["pending"] = None
        if not monitor.get_network_available():
            return False  # der naechste Wechsel bringt das Netz zurueck
        print(f"[xeneon-edge] {what}: network changed — reloading")
        _safe_reload(reload, view, what)
        return False

    def on_change(_monitor, _available) -> None:
        if state["pending"] is not None:
            GLib.source_remove(state["pending"])
        state["pending"] = GLib.timeout_add_seconds(_NETWORK_SETTLE_S, fire)

    state["handler"] = monitor.connect("network-changed", on_change)
    return detach


class _WebPanel(Gtk.Box):
    """Der Rahmen um eine WebView, mit dem Abbau, den das Fenster erwartet.

    window.py ruft ``teardown()`` auf Module, die beim Neubau des Layouts
    nicht wiederverwendet werden — hier haengt das den NetworkMonitor-Handler
    ab, der die View sonst fuer immer festhielte.
    """

    def __init__(self, view: Gtk.Widget, teardown) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("panel")
        self.append(view)
        self._teardown = teardown

    def teardown(self) -> None:
        """Mehrfach aufrufbar."""
        for fn in self._teardown:
            try:
                fn()
            except Exception as e:
                print(f"[xeneon-edge] web panel teardown failed: {e}")
        self._teardown = ()

    def do_dispose(self):  # type: ignore[override]
        self.teardown()
        Gtk.Box.do_dispose(self)


# Zoom des OpenMarket-Moduls, wenn das Layout nichts anderes sagt. Die
# Chart-Seite rechnet mit einem Desktop-Browser; in der rund 1270 px breiten
# Mittelspalte des 2560er-Streifens schnitt sie das Orderbuch rechts ab. Bei
# 72 % sieht sie rund 1760 CSS-Pixel; nachgemessen am 17.10.2026: 80 % zeigt
# Preis und Menge, erst 72 % auch die Total-Spalte des Orderbuchs.
OM_DEFAULT_ZOOM = 72
ZOOM_MIN, ZOOM_MAX = 50, 150


def zoom_from_percent(value, default: int) -> float:
    """Modul-Einstellung ``zoom`` (Prozent, int) als WebKit-Zoomfaktor."""
    try:
        pct = int(value) if value not in (None, "") else int(default)
    except (TypeError, ValueError):
        pct = int(default)
    return max(ZOOM_MIN, min(ZOOM_MAX, pct)) / 100.0


def _try_webview(url: str = "", html: str = "", base: str = "",
                 zoom: float = 1.0) -> Gtk.Widget | None:
    """Panel mit einer View auf ``url``, oder auf ``html`` mit ``base`` als Herkunft.

    Eine Adresse bekommt die persistente Session: sonst waere jeder Login —
    TradingView wie Webmail — nach einem Neustart des Dashboards weg. Das
    eingebettete Widget braucht sie nicht, es meldet sich nirgends an.

    ``zoom`` ist WebKits Seitenzoom (1.0 = 100 %): unter 1 sieht die Seite
    einen breiteren Viewport und bringt mehr unter, Schrift und Chart werden
    kleiner. Wirkt auf das Layout, nicht nur auf den Text.
    """
    WebKit = import_webkit()
    if WebKit is None:
        return None
    try:
        context = make_context(WebKit)
        # reload() bekommt die View uebergeben statt sie einzufangen: der
        # NetworkMonitor haelt seinen Handler laenger, als die View lebt.
        if url:
            view = WebKit.WebView(web_context=context,
                                  network_session=make_session(WebKit))
            what, home = f"page {url[:60]}", url

            def reload(v):
                v.load_uri(url)
        else:
            view = WebKit.WebView(web_context=context)
            what, home = "TradingView widget", base

            def reload(v):
                v.load_html(html, base)
        stop_watchdog = _watch_page_loads(view, reload, what, home)
        _watch_web_process(view, reload, what)
        detach_monitor = _reload_on_network_change(view, reload, what)
        if abs(zoom - 1.0) > 0.001:
            view.set_zoom_level(zoom)
        reload(view)
        view.set_hexpand(True); view.set_vexpand(True)
        return _WebPanel(view, (stop_watchdog, detach_monitor))
    except Exception as e:
        print(f"[xeneon-edge] WebKit init failed: {e}")
        return None


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


NO_WEBKIT = ("Needs WebKitGTK 6.0.\nInstall with:\n\n"
             "  Fedora: sudo dnf install webkitgtk6.0\n"
             "  Arch:   sudo pacman -S webkitgtk-6.0\n"
             "  Debian: sudo apt install gir1.2-webkit-6.0")


def make_tradingview_widget(config: dict | None = None,
                            palette: theme_mod.Palette | None = None) -> Gtk.Widget:
    """TradingView — eigener Chart aus dem Account oder eingebettetes Widget."""
    cfg = config or {}
    url = str(cfg.get("url") or "") if str(cfg.get("mode") or "widget") == "account" else ""
    if url:
        panel = _try_webview(url=url)
    else:
        html = widget_html(palette, cfg)
        panel = _try_webview(html=html, base="https://tradingview.com/")
    if panel is not None:
        return panel
    return _placeholder("TRADINGVIEW", NO_WEBKIT)


def make_web_widget(url: str = "", zoom: float = 1.0) -> Gtk.Widget:
    """Freies Web-Panel: eine Adresse, sonst nichts."""
    if not url:
        return _placeholder(
            "WEB PANEL",
            "No address set. In the editor, click the module and enter a URL "
            "under \u201cAddress\u201d — or use the TradingView or OpenMarket "
            "module if it is about charts.")
    panel = _try_webview(url=url, zoom=zoom)
    return panel if panel is not None else _placeholder("WEB PANEL", NO_WEBKIT)


def make_openmarket_widget(url: str = "", zoom: float = OM_DEFAULT_ZOOM / 100.0) -> Gtk.Widget:
    """OpenMarket: der eigene Chart aus dem Account.

    Technisch ein Web-Panel mit persistenter Session — als eigenes Modul,
    damit es im Editor neben TradingView zur Wahl steht und seinen Chart ueber
    dasselbe Login-Fenster bekommt, statt dass jemand die Adresse aus dem
    Browser abtippen muss. Ein anonymes Widget wie bei TradingView gibt es
    nicht; ohne Adresse bleibt der Platzhalter.
    """
    if not url:
        return _placeholder(
            "OPENMARKET",
            "No chart chosen yet. In the editor, click the module and press "
            "\u201cSign in / choose chart\u201d — or enter the chart's address "
            "(https://openmarket.xyz/chart/\u2026) by hand under "
            "\u201cChart address\u201d.")
    panel = _try_webview(url=url, zoom=zoom)
    return panel if panel is not None else _placeholder("OPENMARKET", NO_WEBKIT)
