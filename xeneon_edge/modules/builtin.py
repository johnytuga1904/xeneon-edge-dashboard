"""Die mitgelieferten Module.

Duenne Huellen um die bestehenden Panels: sie nehmen den ganzen Snapshot
entgegen und reichen ihren Ausschnitt weiter. Bewusst kein Umbau der Panels
selbst — die funktionieren, und Schritt 1 soll am sichtbaren Verhalten nichts
aendern.

Die Einstellungen in ``schema`` sind hier schon deklariert, werden aber erst
mit dem Editor (Schritt 4) ausgewertet. Bis dahin gelten die Defaults.
"""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from . import Field, ModuleSpec, register, register_topbar
from ..ui.panels import CpuPanel, GpuPanel, RamPanel, ProcessPanel, FanPanel
from ..ui.audio_panel import AudioPanel
from ..ui.calendar import CalendarModule
from ..ui.clock import ClockModule
from ..ui.deck import LaunchDeck
from ..ui.mediaplayer import MediaPlayerModule
from ..ui.notes import NotesModule
from ..ui import chart as chart_mod
from ..ui.chart import (make_openmarket_widget, make_tradingview_widget,
                        make_web_widget)
from ..ui import topbar


SENSOR_METRICS = ("cpu", "gpu", "ram", "fans")

# Ueberschrift des aufklappbaren Blocks im TradingView-Formular.
WIDGET_GROUP = "Widget settings"


class SensorsModule(Gtk.Box):
    """CPU + GPU + RAM + Luefter untereinander — oder eine Auswahl davon.

    ``config["metrics"]`` bestimmt, welche Panels gebaut werden; ``needs``
    folgt dieser Auswahl, damit der Aggregator nur liest, was hier auch zu
    sehen ist.
    """

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_vexpand(True)
        # Nicht mit dem Web-Modul um Breite konkurrieren: die Spaltenbreite
        # kommt von FixedWidth, nicht vom Inhalt.
        self.set_hexpand(False)
        self.add_css_class("col-sensors")

        raw = config.get("metrics")
        wanted = [m for m in (raw if isinstance(raw, list) else SENSOR_METRICS)
                  if m in SENSOR_METRICS]
        self.metrics = tuple(wanted) or SENSOR_METRICS
        self.needs = frozenset(self.metrics)

        self.cpu_panel = CpuPanel() if "cpu" in self.metrics else None
        self.gpu_panels: list[GpuPanel] = []
        self._gpu_placeholder = False
        self.gpu_container = None
        if "gpu" in self.metrics:
            self.gpu_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.ram_panel = RamPanel() if "ram" in self.metrics else None
        self.fan_panel = FanPanel() if "fans" in self.metrics else None
        for w in (self.cpu_panel, self.gpu_container, self.ram_panel, self.fan_panel):
            if w is None:
                continue
            w.set_vexpand(True)
            self.append(w)

    def update(self, snap) -> None:
        if self.cpu_panel is not None:
            self.cpu_panel.update(snap.cpu, snap.cpu_name)
        if self.ram_panel is not None:
            self.ram_panel.update(snap.ram)
        if self.fan_panel is not None:
            self.fan_panel.update(snap.fans)
        if self.gpu_container is not None:
            self._update_gpus(snap.gpus)

    def _update_gpus(self, gpus: list[dict]) -> None:
        # Anzahl der GPU-Panels an die gefundenen GPUs anpassen. Eine GPU kann
        # zur Laufzeit verschwinden (Treiber-Neustart), also jedes Mal pruefen.
        # Ohne erkannte GPU steht genau ein Platzhalter-Panel — den nicht jede
        # Sekunde abreissen und neu bauen, nur weil len(gpus) == 0 ist.
        if not gpus and self._gpu_placeholder:
            return
        if len(self.gpu_panels) != len(gpus):
            child = self.gpu_container.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.gpu_container.remove(child)
                child = nxt
            self.gpu_panels = []
            self._gpu_placeholder = False
            for _ in gpus:
                p = GpuPanel()
                self.gpu_container.append(p)
                self.gpu_panels.append(p)
        for panel, gpu in zip(self.gpu_panels, gpus):
            panel.update(gpu)
        # Ohne erkannte GPU bleibt ein leeres Panel stehen, damit die Spalte
        # nicht in sich zusammenfaellt.
        if not gpus and not self.gpu_panels:
            placeholder = GpuPanel()
            placeholder.update(None)
            self.gpu_container.append(placeholder)
            self.gpu_panels.append(placeholder)
            self._gpu_placeholder = True


class ProcessesModule(ProcessPanel):
    def __init__(self, config: dict):
        try:
            rows = int(config.get("count") or ProcessPanel.ROWS)
        except (TypeError, ValueError):
            rows = ProcessPanel.ROWS
        super().__init__(rows=max(4, min(20, rows)))
        self.set_vexpand(True)
        self.set_hexpand(False)

    def update(self, snap) -> None:  # type: ignore[override]
        ProcessPanel.update(self, snap.processes)


class AudioModule(AudioPanel):
    def __init__(self, config: dict):
        super().__init__()
        self.set_hexpand(False)

    def update(self, snap) -> None:  # type: ignore[override]
        AudioPanel.update(self, snap.audio)


class DeckModule(LaunchDeck):
    def __init__(self, config: dict):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(False)

    def update(self, snap) -> None:
        """Das Deck haengt nicht an Sensordaten — es wird von app.py befuellt."""


class _WebHolder(Gtk.Box):
    """Gemeinsamer Unterbau von Web-Panel und TradingView.

    Haelt die View in einem Halter, damit ein Wechsel nur das Kind tauschen
    muss und die Zelle im Grid stehen bleibt.
    """

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._config = dict(config)
        self._palette = config.get("_palette")
        self.append(self._make())

    def _make(self) -> Gtk.Widget:
        raise NotImplementedError

    def _rebuild(self) -> None:
        child = self.get_first_child()
        if child is not None:
            self.remove(child)
        self.append(self._make())

    def update(self, snap) -> None:
        """Webinhalt laedt sich selbst — keine Sensordaten noetig."""


class WebModule(_WebHolder):
    """WebKit-View auf eine frei gewaehlte Adresse."""

    def _make(self) -> Gtk.Widget:
        return make_web_widget(str(self._config.get("url", "") or ""),
                               zoom=chart_mod.zoom_from_percent(self._config.get("zoom"), 100))

    def set_url(self, url: str) -> None:
        url = url or ""
        if url == str(self._config.get("url", "") or ""):
            return
        self._config["url"] = url
        self._rebuild()


class OpenMarketModule(_WebHolder):
    """OpenMarket: der eigene Chart aus dem Account, Adresse aus dem Login."""

    def _make(self) -> Gtk.Widget:
        return make_openmarket_widget(
            str(self._config.get("url", "") or ""),
            zoom=chart_mod.zoom_from_percent(self._config.get("zoom"), chart_mod.OM_DEFAULT_ZOOM))


class TradingViewModule(_WebHolder):
    """TradingView: eingebettetes Widget oder der eigene Chart nach Login."""

    def _make(self) -> Gtk.Widget:
        return make_tradingview_widget(self._config, self._palette)

    def set_palette(self, palette) -> None:
        """Theme-Wechsel: nur das anonyme Widget wird neu gefaerbt.

        Die volle Chart-Seite hat ihr eigenes Theme; sie neu zu laden
        wuerde nur den mehrere Sekunden langen Seitenaufbau wiederholen.
        """
        self._palette = palette
        if str(self._config.get("mode") or "widget") != "account":
            self._rebuild()


register(ModuleSpec(
    type_id="sensors",
    label="Sensors",
    factory=SensorsModule,
    needs=frozenset({"cpu", "gpu", "ram", "fans"}),
    default_width=460,
    schema=(
        Field("metrics", "Displayed values", "list",
              default=["cpu", "gpu", "ram", "fans"],
              options=(("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM"), ("fans", "Fans")),
              help="What is not displayed, the aggregator does not read either."),
    ),
))

register(ModuleSpec(
    type_id="processes",
    label="Processes",
    factory=ProcessesModule,
    needs=frozenset({"processes"}),
    default_width=420,
    schema=(
        Field("count", "Number of rows", "int", default=14, min=4, max=20),
    ),
))

register(ModuleSpec(
    type_id="audio",
    label="Audio",
    factory=AudioModule,
    needs=frozenset({"audio"}),
    default_width=420,
))

register(ModuleSpec(
    type_id="deck",
    label="Launch Deck",
    factory=DeckModule,
    default_width=430,
    singleton=True,
))

register(ModuleSpec(
    type_id="clock",
    label="Clock",
    factory=ClockModule,
    default_width=420,
    schema=(
        Field("mode", "Display", "select", default="datetime",
              options=(("datetime", "Time and date"), ("time", "Time only"),
                       ("zones", "Time zones"))),
        Field("seconds", "Show seconds", "bool", default=False),
        Field("zones", "Time zones", "text",
              default="London=Europe/London, New York=America/New_York, Tokyo=Asia/Tokyo",
              show_if=("mode", ("zones",)),
              help="Format: Name=Zone, separated by commas. Zones as in "
                   "/usr/share/zoneinfo, e.g. Europe/Zurich."),
    ),
))

register(ModuleSpec(
    type_id="calendar",
    label="Calendar",
    factory=CalendarModule,
    default_width=440,
    schema=(
        Field("first_day", "Week starts on", "select", default="monday",
              options=(("monday", "Monday"), ("sunday", "Sunday"))),
        Field("week_numbers", "Show week numbers", "bool", default=False),
    ),
))

register(ModuleSpec(
    type_id="media",
    label="Playback",
    factory=MediaPlayerModule,
    default_width=460,
    schema=(
        Field("player", "Player", "text", default="",
              help="Empty = whichever one is currently playing. Otherwise part of "
                   "a name, e.g. spotify, mpv, firefox."),
        Field("show_cover", "Show cover", "bool", default=True,
              help="Only when the module is large enough; title, artist and buttons "
                   "always stay."),
        Field("music_dir", "Music folder", "dir", default="",
              help="When set, the module plays this folder itself — no other "
                   "program needed; a fourth button starts it. Subfolders are "
                   "included; of video files only the audio track plays. "
                   "Anything playing elsewhere takes precedence."),
        Field("shuffle", "Shuffle", "bool", default=False,
              show_if=("music_dir", ()),
              help="Shuffles the music folder once at start."),
    ),
))

register(ModuleSpec(
    type_id="notes",
    label="Notes",
    factory=NotesModule,
    default_width=460,
    schema=(
        Field("path", "File", "path", default="",
              help="Text, Markdown or JSON file. Display only, never written; "
                   "when it changes, the module reloads it. "
                   "Tapping a line copies it."),
    ),
))

register(ModuleSpec(
    type_id="web",
    label="Web panel",
    factory=WebModule,
    schema=(
        Field("url", "Address", "text", default="",
              help="Full address including https://. The page runs in its own "
                   "WebKit process (roughly 150–300 MB) and keeps its login "
                   "across restarts."),
        Field("zoom", "Zoom (%)", "int", default=100,
              min=chart_mod.ZOOM_MIN, max=chart_mod.ZOOM_MAX,
              help="Page zoom. Below 100 the page sees more width and fits "
                   "more in; text gets smaller."),
    ),
))

register(ModuleSpec(
    type_id="openmarket",
    label="OpenMarket",
    factory=OpenMarketModule,
    schema=(
        Field("url", "Chart address", "text", default="",
              help="Filled in by \"Sign in / choose chart\"; an address like "
                   "https://openmarket.xyz/chart/\u2026 can also be entered by "
                   "hand. The page costs around 1 GB of memory and permanently "
                   "about a third of a core — considerably more than TradingView."),
        Field("zoom", "Zoom (%)", "int", default=chart_mod.OM_DEFAULT_ZOOM,
              min=chart_mod.ZOOM_MIN, max=chart_mod.ZOOM_MAX,
              help="Page zoom. The chart page is built for a wide browser; at 100 "
                   "the order book is cut off on the right in the centre column, "
                   "at 80 the Total column is still missing, at 72 everything fits."),
    ),
))

register(ModuleSpec(
    type_id="tradingview",
    label="TradingView",
    factory=TradingViewModule,
    schema=(
        Field("mode", "Source", "select", default="widget",
              options=(("widget", "Embedded widget"),
                       ("account", "Own chart")),
              help="The widget knows no account and no saved layouts; "
                   "your own chart costs around 1 GB of memory."),
        Field("url", "Chart address", "text", default="",
              show_if=("mode", ("account",)),
              help="Filled in by \"Sign in / choose chart\", but can also be "
                   "entered by hand."),
        # Die folgenden gelten nur fuers Widget: der eigene Chart bringt Symbol,
        # Intervall und Indikatoren aus dem Account mit. Deshalb sind sie bei
        # "Eigener Chart" ganz weg und sonst hinter einem Aufklapper — sieben
        # Felder auf einmal waren mehr, als der erste Blick vertraegt.
        Field("symbol", "Symbol", "text", default=chart_mod.TV_DEFAULTS["symbol"],
              group=WIDGET_GROUP, show_if=("mode", ("widget",)),
              help="Exchange and ticker, e.g. BINANCE:BTCUSDT, NASDAQ:AAPL, SIX:NESN."),
        Field("interval", "Interval", "select",
              default=chart_mod.TV_DEFAULTS["interval"],
              options=chart_mod.TV_INTERVALS,
              group=WIDGET_GROUP, show_if=("mode", ("widget",))),
        Field("timezone", "Time zone", "text",
              default=chart_mod.TV_DEFAULTS["timezone"],
              group=WIDGET_GROUP, show_if=("mode", ("widget",)),
              help="Zone as in /usr/share/zoneinfo, e.g. Europe/Zurich, "
                   "America/New_York."),
        Field("studies", "Indicators", "list",
              default=list(chart_mod.TV_DEFAULTS["studies"]),
              options=chart_mod.TV_STUDIES,
              group=WIDGET_GROUP, show_if=("mode", ("widget",)),
              help=f"At most {chart_mod.TV_MAX_STUDIES} (volume does not count) "
                   "— the free widget accepts no more."),
        Field("toolbars", "Show toolbars", "bool", default=True,
              group=WIDGET_GROUP, show_if=("mode", ("widget",)),
              help="Symbol search and drawing tools. Without a keyboard at the "
                   "strip they are often just in the way."),
    ),
))


# ----- Topbar -----

register_topbar(ModuleSpec(
    type_id="brand", label="Brand", factory=topbar.BrandWidget, singleton=True,
    schema=(Field("subtitle", "Subtitle", "text", default="COMMAND CENTER"),),
))
register_topbar(ModuleSpec(
    type_id="status", label="Sensor status", factory=topbar.StatusPill, singleton=True,
))
register_topbar(ModuleSpec(
    type_id="net", label="Network", factory=topbar.NetPill, singleton=True,
))
register_topbar(ModuleSpec(
    type_id="clock", label="Clock", factory=topbar.ClockWidget,
    schema=(Field("seconds", "Show seconds", "bool", default=False),),
))
register_topbar(ModuleSpec(
    type_id="weather", label="Weather", factory=topbar.WeatherPill,
    schema=(
        Field("lat", "Latitude", "float", default=None, min=-90, max=90,
              help="Open-Meteo, e.g. 47.3769 for Zurich"),
        Field("lon", "Longitude", "float", default=None, min=-180, max=180,
              help="e.g. 8.5417"),
        Field("label", "Place name", "text", default="", help="Tooltip only"),
    ),
))
register_topbar(ModuleSpec(
    type_id="match", label="Next fixture", factory=topbar.MatchPill,
    schema=(
        Field("league", "League (ESPN code)", "text", default="",
              help="eng.1, ger.1, esp.1, ita.1, por.1, uefa.champions …"),
        Field("team", "Team ID (ESPN)", "text", default="",
              help="Number from the team's ESPN URL, e.g. 359 for Arsenal"),
        Field("short", "Short code", "text", default="", help="Shown large in the pill, e.g. ARS"),
    ),
))
