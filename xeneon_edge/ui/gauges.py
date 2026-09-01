"""Tiny horizontal bar gauge: a track box with a manually-allocated fill child."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk  # noqa: E402


class BarGauge(Gtk.Box):
    """A track-and-fill bar.

    ``set_value(0..100)`` sets the fill width as a percentage of the track.

    The fill is allocated by hand in :meth:`do_size_allocate` and the widget
    reports a **zero** horizontal size, so a full bar never contributes to the
    minimum width of its parents. Earlier versions sized the fill with
    ``set_size_request``; because ``Gtk.Box`` measures through its layout
    manager, that request propagated upward and a 100% bar visibly widened the
    whole sensor column (which then shrank again as load dropped). Dropping the
    box layout manager makes our ``do_measure`` / ``do_size_allocate`` vfuncs
    authoritative, decoupling the fill from layout entirely.
    """

    __gtype_name__ = "XeBarGauge"

    def __init__(self, *, hot_threshold: float = 80.0, warm_threshold: float = 50.0):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        # Remove GtkBoxLayout so the fill's geometry can't drive measurement.
        self.set_layout_manager(None)
        self.add_css_class("gauge")
        self._fill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._fill.add_css_class("gauge-fill")
        self._fill.set_parent(self)
        self.set_hexpand(True)
        self._hot = hot_threshold
        self._warm = warm_threshold
        self._value = 0.0

    def set_value(self, value: float | None) -> None:
        if value is None:
            value = 0.0
        value = max(0.0, min(100.0, float(value)))
        self._value = value
        self.remove_css_class("warm")
        self.remove_css_class("hot")
        if value >= self._hot:
            self.add_css_class("hot")
        elif value >= self._warm:
            self.add_css_class("warm")
        # Only the fill geometry changes — no size negotiation needed.
        self.queue_allocate()

    def do_measure(self, orientation, for_size):  # type: ignore[override]
        if orientation == Gtk.Orientation.HORIZONTAL:
            # Never let the fill drive width; hexpand still spans the row.
            return (0, 0, -1, -1)
        # Height comes from the fill's CSS min-height.
        minimum, natural, _, _ = self._fill.measure(orientation, for_size)
        return (minimum, natural, -1, -1)

    def do_size_allocate(self, width: int, height: int, baseline: int):  # type: ignore[override]
        fill_w = max(0, int(width * self._value / 100.0))
        rect = Gdk.Rectangle()
        rect.x = 0
        rect.y = 0
        rect.width = fill_w
        rect.height = height
        self._fill.size_allocate(rect, -1)

    def do_dispose(self):  # type: ignore[override]
        fill = getattr(self, "_fill", None)
        if fill is not None:
            fill.unparent()
            self._fill = None
        Gtk.Box.do_dispose(self)
