"""Kalender: ein Monatsraster, sonst nichts.

Bewusst ohne Termine und ohne Verbindung nach draussen. Ein Kalender mit
Terminen braucht .ics-Zerlegung, und Wiederholungsregeln und Zeitzonen von
Hand sind eine Falle — das steht so in docs/ARCHITECTURE.md. Hier geht es um
etwas anderes: nachsehen, welcher Wochentag der 23. ist. Dafuer braucht es
keine Bibliothek und keinen Kontozugang.

Gezeichnet wie die Uhr (siehe ui/drawing.py), damit das Raster die Spalte
ausfuellt, die es im Layout bekommt, statt in einer Ecke zu kleben.
"""
from __future__ import annotations
import calendar as calendar_mod
from datetime import date

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

from .drawing import REF_PX, fit, layout, rgba, rounded_rect, set_source

# Immer sechs Wochenzeilen zeichnen, auch wenn der Monat mit fuenf auskommt.
# Sonst aendert sich die Zeilenhoehe von Monat zu Monat, und ein Kalender, der
# im Maerz anders aussieht als im Februar, wirkt kaputt.
WEEK_ROWS = 6

FIRST_DAYS = {"monday": calendar_mod.MONDAY, "sunday": calendar_mod.SUNDAY}


def month_grid(today: date, first_day: int) -> list[list[date]]:
    """Sechs Wochen mit je sieben Tagen um ``today`` herum.

    ``monthdatescalendar`` liefert je nach Monat vier bis sechs Wochen und
    fuellt Rand-Tage aus den Nachbarmonaten auf. Auf sechs verlaengert wird
    hinten, indem weitergezaehlt wird.
    """
    weeks = calendar_mod.Calendar(first_day).monthdatescalendar(today.year, today.month)
    while len(weeks) < WEEK_ROWS:
        last = weeks[-1][-1]
        weeks.append([date.fromordinal(last.toordinal() + 1 + i) for i in range(7)])
    return weeks[:WEEK_ROWS]


def weekday_labels(first_day: int) -> list[str]:
    """Kurznamen der Wochentage, beginnend beim gewaehlten ersten Tag.

    Ueber strftime und nicht ueber calendar.day_abbr, damit sie derselben
    Spracheinstellung folgen wie das Datum im Uhr-Modul.
    """
    # 2024-01-01 war ein Montag, also ist Ordnungszahl + Wochentag direkt der
    # gewuenschte Tag.
    monday = date(2024, 1, 1).toordinal()
    return [date.fromordinal(monday + (first_day + i) % 7).strftime("%a").upper()
            for i in range(7)]


class CalendarModule(Gtk.Box):
    __gtype_name__ = "XeCalendarModule"

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("panel")
        self.add_css_class("calendar-module")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.needs = frozenset()

        self.first_day = FIRST_DAYS.get(str(config.get("first_day") or "monday"),
                                        calendar_mod.MONDAY)
        self.week_numbers = bool(config.get("week_numbers"))
        self._palette = config.get("_palette")
        self._shown = date.today()

        self.area = Gtk.DrawingArea()
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        self.append(self.area)

    # ----- Zeichnen -----

    def _font(self) -> Pango.FontDescription:
        return self.get_pango_context().get_font_description().copy()

    def _accent(self, fallback):
        """Akzentfarbe aus der Palette, sonst die Vordergrundfarbe.

        Ueber die Palette und nicht ueber eine CSS-Klasse, weil die
        DrawingArea nur ihre eigene Farbe kennt; set_palette() haelt sie beim
        Theme-Wechsel aktuell.
        """
        if self._palette is None:
            return fallback
        return rgba(getattr(self._palette, "accent", ""), fallback)

    def _on_accent(self, fallback):
        if self._palette is None:
            return fallback
        return rgba(getattr(self._palette, "on_accent", ""), fallback)

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        colour = area.get_color()
        desc = self._font()
        today = date.today()
        pad = max(4.0, min(width, height) * 0.04)
        w, h = width - 2 * pad, height - 2 * pad
        if w <= 0 or h <= 0:
            return

        # Kopfzeile, Wochentage, dann sechs Wochen.
        head_h = h * 0.16
        days_h = h * 0.09
        grid_h = h - head_h - days_h

        bold = desc.copy()
        bold.set_weight(Pango.Weight.HEAVY)
        head_text = today.strftime("%B %Y").upper()
        head_layout, hw, hh = fit(cr, bold, head_text, w, head_h * 0.85)
        set_source(cr, colour)
        cr.move_to(pad + (w - hw) / 2, pad + (head_h - hh) / 2)
        PangoCairo.show_layout(cr, head_layout)

        cols = 8 if self.week_numbers else 7
        cell_w = w / cols
        cell_h = grid_h / WEEK_ROWS
        # Die Wochennummern stehen in der ersten Spalte, das Raster beginnt
        # dann eine Spalte weiter rechts.
        grid_x = pad + (cell_w if self.week_numbers else 0)

        # Wochentage. 0.86 der Zellbreite, damit zwischen zwei Kuerzeln noch
        # Luft bleibt — buendig aneinander gesetzt lesen sie sich als ein Wort.
        small = desc.copy()
        small.set_weight(Pango.Weight.NORMAL)
        names = weekday_labels(self.first_day)
        day_px = self._cell_px(cr, small, max(names, key=len), cell_w * 0.86, days_h * 0.8)
        for i, name in enumerate(names):
            lay, lw, lh = layout(cr, small, name, day_px)
            set_source(cr, colour, 0.55)
            cr.move_to(grid_x + i * cell_w + (cell_w - lw) / 2,
                       pad + head_h + (days_h - lh) / 2)
            PangoCairo.show_layout(cr, lay)

        # Tage. Eine Groesse fuer alle Zellen, sonst tanzen die Zahlen.
        num_px = self._cell_px(cr, bold, "00", cell_w * 0.8, cell_h * 0.55)
        weeks = month_grid(today, self.first_day)
        top0 = pad + head_h + days_h
        accent = self._accent(colour)
        on_accent = self._on_accent(colour)

        for r, week in enumerate(weeks):
            top = top0 + r * cell_h
            if self.week_numbers:
                # ISO-Woche des Montags in dieser Zeile: bei Sonntagsstart
                # gehoert week[0] noch zur Vorwoche.
                monday = next((d for d in week if d.weekday() == 0), week[0])
                lay, lw, lh = layout(cr, small, f"{monday.isocalendar().week:02d}",
                                     num_px * 0.7)
                set_source(cr, colour, 0.35)
                cr.move_to(pad + (cell_w - lw) / 2, top + (cell_h - lh) / 2)
                PangoCairo.show_layout(cr, lay)
            for c, day in enumerate(week):
                lay, lw, lh = layout(cr, bold, str(day.day), num_px)
                x = grid_x + c * cell_w + (cell_w - lw) / 2
                y = top + (cell_h - lh) / 2
                if day == today:
                    # Heute bekommt eine gefuellte Flaeche statt nur einer
                    # anderen Schriftfarbe: auf einem Streifen, auf den man im
                    # Vorbeigehen schaut, muss das aus zwei Metern zu sehen sein.
                    box = min(cell_w, cell_h) * 0.82
                    rounded_rect(cr, grid_x + c * cell_w + (cell_w - box) / 2,
                                 top + (cell_h - box) / 2, box, box, box * 0.22)
                    set_source(cr, accent)
                    cr.fill()
                    set_source(cr, on_accent)
                elif day.month != today.month:
                    set_source(cr, colour, 0.28)
                else:
                    set_source(cr, colour)
                cr.move_to(x, y)
                PangoCairo.show_layout(cr, lay)

    def _cell_px(self, cr, desc, sample: str, max_w: float, max_h: float) -> float:
        """Schriftgroesse, bei der ``sample`` in ``max_w`` x ``max_h`` passt.

        Eine Groesse fuer alle Zellen einer Reihe, gemessen am breitesten
        Fall: unterschiedlich grosse Zahlen nebeneinander sehen aus wie ein
        Fehler. Die Probe muss deshalb wirklich der breiteste Text sein — mit
        "00" gemessene Wochentagskuerzel ("MON") liefen ineinander.
        """
        _, ref_w, ref_h = layout(cr, desc, sample, REF_PX)
        if ref_w <= 0 or ref_h <= 0:
            return 8.0
        return max(8.0, REF_PX * min(max_w / ref_w, max_h / ref_h))

    # ----- Fenster-Schnittstelle -----

    def set_palette(self, palette) -> None:
        self._palette = palette
        self.area.queue_draw()

    def tick(self) -> None:
        # Nur zeichnen, wenn sich das Datum geaendert hat — ein Raster, das
        # sich sekuendlich neu malt, kostet ohne Grund.
        today = date.today()
        if today != self._shown:
            self._shown = today
            self.area.queue_draw()

    def update(self, snap) -> None:
        """Der Kalender kennt nur das Datum, keine Sensordaten."""
