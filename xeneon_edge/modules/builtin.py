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

from . import Field, ModuleSpec, register
from ..ui.panels import CpuPanel, GpuPanel, RamPanel, ProcessPanel, FanPanel
from ..ui.audio_panel import AudioPanel
from ..ui.deck import LaunchDeck
from ..ui.chart import make_chart_widget


SENSOR_METRICS = ("cpu", "gpu", "ram", "fans")


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
        if len(self.gpu_panels) != len(gpus):
            child = self.gpu_container.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.gpu_container.remove(child)
                child = nxt
            self.gpu_panels = []
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


class ProcessesModule(ProcessPanel):
    def __init__(self, config: dict):
        super().__init__()
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


class WebModule(Gtk.Box):
    """WebKit-View auf eine URL.

    Haelt die View in einem Halter, damit ein URL-Wechsel nur das Kind
    tauschen muss und die Zelle im Grid stehen bleibt. Leere URL = das
    eingebettete TradingView-Widget (der bisherige Default).
    """

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._url = str(config.get("url", "") or "")
        self._palette = config.get("_palette")
        self.append(make_chart_widget(self._url, self._palette))

    def set_url(self, url: str) -> None:
        url = url or ""
        if url == self._url:
            return
        self._url = url
        self._rebuild()

    def set_palette(self, palette) -> None:
        """Theme-Wechsel: nur das anonyme Widget wird neu gefaerbt.

        Die volle Chart-Seite hat ihr eigenes Theme; sie neu zu laden
        wuerde nur den mehrere Sekunden langen Seitenaufbau wiederholen.
        """
        self._palette = palette
        if not self._url:
            self._rebuild()

    def _rebuild(self) -> None:
        child = self.get_first_child()
        if child is not None:
            self.remove(child)
        self.append(make_chart_widget(self._url, self._palette))

    def update(self, snap) -> None:
        """Webinhalt laedt sich selbst — keine Sensordaten noetig."""


register(ModuleSpec(
    type_id="sensors",
    label="Sensoren",
    factory=SensorsModule,
    needs=frozenset({"cpu", "gpu", "ram", "fans"}),
    default_width=460,
    schema=(
        Field("metrics", "Angezeigte Werte", "list",
              default=["cpu", "gpu", "ram", "fans"],
              help="Was nicht angezeigt wird, wird spaeter auch nicht gelesen."),
    ),
))

register(ModuleSpec(
    type_id="processes",
    label="Prozesse",
    factory=ProcessesModule,
    needs=frozenset({"processes"}),
    default_width=420,
    schema=(
        Field("count", "Anzahl Zeilen", "int", default=14),
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
    label="Launch-Deck",
    factory=DeckModule,
    default_width=430,
    singleton=True,
))

register(ModuleSpec(
    type_id="web",
    label="Web-Panel",
    factory=WebModule,
    schema=(
        Field("url", "Adresse", "text", default="",
              help="Leer = eingebettetes TradingView-Widget ohne Login."),
    ),
))
