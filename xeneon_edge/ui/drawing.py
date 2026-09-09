"""Gemeinsame Helfer fuer Module, die sich selbst zeichnen.

Uhr und Kalender stapeln keine Labels, sondern malen auf eine
``Gtk.DrawingArea``: eine Schriftgroesse, die aus der zugeteilten Flaeche
kommt, aendert am Label auch dessen *Mindest*groesse, und die Spalte wuerde
sich bei jedem Tick neu ausmessen. Eine DrawingArea meldet aus ihrem Inhalt
keine Mindestgroesse und darf deshalb genau auf die Flaeche rechnen, die sie
bekommt.
"""
from __future__ import annotations
import math

import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Pango, PangoCairo  # noqa: E402

# Bezugsgroesse zum Ausmessen. Pango skaliert linear, also einmal bei 100 px
# messen und den Faktor ausrechnen ist genauso genau wie eine Suche und
# kostet ein Layout statt zehn.
REF_PX = 100.0


def layout(cr, desc: Pango.FontDescription, text: str, px: float):
    """Ein Pango-Layout in absoluter Pixelgroesse, plus seine Masse."""
    font = desc.copy()
    font.set_absolute_size(max(1.0, px) * Pango.SCALE)
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(font)
    lay.set_text(text, -1)
    w, h = lay.get_pixel_size()
    return lay, w, h


def fit(cr, desc: Pango.FontDescription, text: str, max_w: float, max_h: float):
    """Groesstes Layout fuer ``text``, das in ``max_w`` x ``max_h`` passt."""
    _, ref_w, ref_h = layout(cr, desc, text or " ", REF_PX)
    if ref_w <= 0 or ref_h <= 0:
        return layout(cr, desc, text, 8.0)
    px = REF_PX * min(max_w / ref_w, max_h / ref_h)
    return layout(cr, desc, text, max(8.0, px))


def set_source(cr, colour: Gdk.RGBA, alpha: float = 1.0) -> None:
    cr.set_source_rgba(colour.red, colour.green, colour.blue, colour.alpha * alpha)


def rgba(value: str, fallback: Gdk.RGBA | None = None) -> Gdk.RGBA:
    """``"#rrggbb"`` aus einer Palette in ein ``Gdk.RGBA``."""
    colour = Gdk.RGBA()
    if colour.parse(str(value or "")):
        return colour
    if fallback is not None:
        return fallback
    colour.parse("#ffffff")
    return colour


def rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    """Pfad fuer ein abgerundetes Rechteck — Cairo kennt keins."""
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
