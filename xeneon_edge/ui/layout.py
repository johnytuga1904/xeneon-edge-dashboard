"""Layout helpers — containers whose geometry can't be pushed around by content."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


class FixedWidth(Gtk.Widget):
    """Bin that reports a constant width, whatever the child asks for.

    ``set_size_request`` only sets a *minimum*: as soon as a value string grows
    ("1.2 GB" → "12.4 GB", a longer process name, "100%" instead of "9%") the
    child's natural width grows with it and the whole column shifts sideways.
    Reporting ``(width, width)`` horizontally turns the column geometry into a
    constant — the same trick :class:`BarGauge` uses to keep its fill out of
    size negotiation.
    """

    __gtype_name__ = "XeFixedWidth"

    def __init__(self, child: Gtk.Widget, width: int):
        super().__init__()
        # No layout manager: gtk_widget_measure() short-circuits to the layout
        # manager when one is set, which would swallow our do_measure override.
        self.set_layout_manager(None)
        self._width = int(width)
        self._child = child
        self.set_hexpand(False)
        self.set_vexpand(True)
        child.set_parent(self)

    def do_measure(self, orientation, for_size):  # type: ignore[override]
        if orientation == Gtk.Orientation.HORIZONTAL:
            return (self._width, self._width, -1, -1)
        # Height is measured for our fixed width, never for the child's wish.
        minimum, natural, _, _ = self._child.measure(orientation, self._width)
        return (minimum, natural, -1, -1)

    def do_size_allocate(self, width: int, height: int, baseline: int):  # type: ignore[override]
        self._child.allocate(width, height, baseline, None)

    def do_dispose(self):  # type: ignore[override]
        child = getattr(self, "_child", None)
        if child is not None:
            child.unparent()
            self._child = None
        Gtk.Widget.do_dispose(self)
