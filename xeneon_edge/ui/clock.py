"""Uhr als Spalten-Modul — der Streifen als grosse Uhr.

Die Topbar hat ihre eigene kompakte Uhr (ui/topbar.py); die bleibt, wie sie
ist. Dieses Modul ist die grosse Fassung und kennt drei Betriebsarten, im
Editor umschaltbar: Zeit mit Datum, nur Zeit, oder mehrere Zeitzonen
untereinander.

Gezeichnet statt gestapelt: eine Schrift, deren Groesse von der zugeteilten
Flaeche abhaengt, aendert als Label auch die Mindestgroesse des Labels — die
Spalte wuerde sich bei jedem Tick neu ausmessen und im schlimmsten Fall
zwischen zwei Groessen pendeln. Eine DrawingArea meldet keine Mindestgroesse
aus ihrem Inhalt und darf deshalb exakt auf die Flaeche rechnen, die sie
bekommt.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

from .drawing import REF_PX, fit as _fit, layout as _layout, set_source

MODES = ("datetime", "time", "zones")

# Anteil der Hoehe, den die Zeit in "datetime" bekommt. Der Rest geht an das
# Datum; die Luecke dazwischen ist in beiden enthalten.
_TIME_SHARE = 0.66


def parse_zones(raw: str) -> list[tuple[str, ZoneInfo | None]]:
    """``"Zuerich=Europe/Zurich, London=Europe/London"`` in Paare zerlegen.

    Trennzeichen sind Komma und Zeilenumbruch, damit im Editor beides geht.
    Ohne ``=`` gilt der ganze Eintrag als Zone und der letzte Pfadteil als
    Beschriftung (``America/New_York`` wird zu ``NEW YORK``). Eine unbekannte
    Zone wird uebersprungen statt das Modul scheitern zu lassen — der Tippfehler
    faellt am fehlenden Eintrag auf, und die uebrigen Zeilen bleiben nutzbar.
    """
    out: list[tuple[str, ZoneInfo | None]] = []
    for chunk in str(raw or "").replace("\n", ",").split(","):
        entry = chunk.strip()
        if not entry:
            continue
        label, _, zone_name = entry.partition("=")
        if not zone_name:
            zone_name, label = label, label.rsplit("/", 1)[-1].replace("_", " ")
        try:
            zone = ZoneInfo(zone_name.strip())
        except (ZoneInfoNotFoundError, ValueError, OSError) as e:
            print(f"[xeneon-edge] Uhr: Zeitzone '{zone_name.strip()}' unbekannt ({e})")
            continue
        out.append((label.strip().upper(), zone))
    return out


class ClockModule(Gtk.Box):
    __gtype_name__ = "XeClockModule"

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("panel")
        self.add_css_class("clock-module")
        self.set_hexpand(True)
        self.set_vexpand(True)
        # Die Uhr haengt an keinem Sensor: was der Aggregator liest, geht sie
        # nichts an.
        self.needs = frozenset()

        mode = str(config.get("mode") or "datetime")
        self.mode = mode if mode in MODES else "datetime"
        self.seconds = bool(config.get("seconds"))
        self.zones = parse_zones(config.get("zones") or "")

        self.area = Gtk.DrawingArea()
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        self.append(self.area)

    # ----- Zeichnen -----

    def _font(self) -> Pango.FontDescription:
        """Schrift des Fensters uebernehmen, nur schwerer.

        So folgt die Uhr der font-family aus style.css, ohne sie zu kennen.
        """
        desc = self.get_pango_context().get_font_description().copy()
        desc.set_weight(Pango.Weight.HEAVY)
        return desc

    def _time_text(self, now: datetime) -> str:
        return now.strftime("%H:%M:%S" if self.seconds else "%H:%M")

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        colour = area.get_color()
        desc = self._font()
        now = datetime.now()
        # Rand, damit die Ziffern nicht am Panelrahmen kleben.
        pad = max(6.0, min(width, height) * 0.06)
        inner_w, inner_h = width - 2 * pad, height - 2 * pad
        if inner_w <= 0 or inner_h <= 0:
            return

        if self.mode == "zones":
            self._draw_zones(cr, desc, colour, pad, inner_w, inner_h)
        elif self.mode == "time":
            self._draw_centred(cr, desc, colour, self._time_text(now),
                               pad, inner_w, inner_h)
        else:
            self._draw_datetime(cr, desc, colour, now, pad, inner_w, inner_h)

    def _draw_centred(self, cr, desc, colour, text, pad, w, h) -> None:
        layout, tw, th = _fit(cr, desc, text, w, h)
        set_source(cr, colour)
        cr.move_to(pad + (w - tw) / 2, pad + (h - th) / 2)
        PangoCairo.show_layout(cr, layout)

    def _draw_datetime(self, cr, desc, colour, now, pad, w, h) -> None:
        gap = h * 0.04
        time_h = (h - gap) * _TIME_SHARE
        date_h = (h - gap) - time_h

        time_layout, tw, th = _fit(cr, desc, self._time_text(now), w, time_h)
        # Datum in normaler Staerke: zwei fette Zeilen uebereinander lesen
        # sich als ein Block, die Uhrzeit soll aber das Auge zuerst treffen.
        date_desc = desc.copy()
        date_desc.set_weight(Pango.Weight.NORMAL)
        date_text = now.strftime("%A, %d %B").upper()
        date_layout, dw, dh = _fit(cr, date_desc, date_text, w, date_h)

        block_h = th + gap + dh
        top = pad + (h - block_h) / 2
        set_source(cr, colour)
        cr.move_to(pad + (w - tw) / 2, top)
        PangoCairo.show_layout(cr, time_layout)
        # Gedaempft, wie ".clock-date" in der Topbar.
        set_source(cr, colour, 0.55)
        cr.move_to(pad + (w - dw) / 2, top + th + gap)
        PangoCairo.show_layout(cr, date_layout)

    def _draw_zones(self, cr, desc, colour, pad, w, h) -> None:
        zones = self.zones or [("LOCAL", None)]
        now_utc = datetime.now().astimezone()
        rows = [(label, (now_utc.astimezone(zone) if zone is not None else now_utc))
                for label, zone in zones]

        row_h = h / len(rows)
        gap = max(8.0, w * 0.04)
        # Eine Groesse fuer alle Zeilen: unterschiedlich hohe Ziffern in
        # untereinanderstehenden Zeilen sehen aus wie ein Fehler. Deshalb die
        # laengste Beschriftung und die laengste Zeit zusammen ausmessen und
        # den knappsten Fall bestimmen.
        widest = max(rows, key=lambda r: len(r[0]))[0]
        sample = f"{widest}{' ' * 2}{self._time_text(rows[0][1])}"
        _, ref_w, ref_h = _layout(cr, desc, sample, REF_PX)
        if ref_w <= 0 or ref_h <= 0:
            return
        px = REF_PX * min((w - gap) / ref_w, (row_h * 0.72) / ref_h)
        px = max(8.0, px)

        label_desc = desc.copy()
        label_desc.set_weight(Pango.Weight.NORMAL)
        for i, (label, when) in enumerate(rows):
            top = pad + i * row_h
            lay_t, tw, th = _layout(cr, desc, self._time_text(when), px)
            lay_l, lw, lh = _layout(cr, label_desc, label, px * 0.62)
            base = top + (row_h - th) / 2
            set_source(cr, colour, 0.55)
            # An der Grundlinie der Ziffern ausrichten, nicht oben: die
            # Beschriftung ist kleiner und haengt sonst in der Luft.
            cr.move_to(pad, base + (th - lh))
            PangoCairo.show_layout(cr, lay_l)
            set_source(cr, colour)
            cr.move_to(pad + w - tw, base)
            PangoCairo.show_layout(cr, lay_t)

    # ----- Fenster-Schnittstelle -----

    def tick(self) -> None:
        self.area.queue_draw()

    def update(self, snap) -> None:
        """Die Uhr braucht keine Sensordaten; tick() zeichnet sie."""
