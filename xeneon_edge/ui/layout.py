"""Layout helpers — containers whose geometry can't be pushed around by content."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gtk, Gsk, Graphene  # noqa: E402


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


class WeightedColumn(Gtk.Widget):
    """Vertikaler Stapel, der die Hoehe nach Gewichten verteilt.

    ``Gtk.Box`` kennt keine Anteile, und ein homogenes ``Gtk.Grid`` verlangt
    fuer jede Zeile die Mindesthoehe der groessten — bei Prozessliste ueber
    Audio wurde die Spalte damit hoeher als der Streifen. Hier ist das Minimum
    die Summe der Kinder, und die Verteilung folgt den Gewichten, solange kein
    Kind unter sein Minimum faellt.
    """

    __gtype_name__ = "XeWeightedColumn"

    def __init__(self, spacing: int = 6):
        super().__init__()
        self.set_layout_manager(None)
        self._spacing = spacing
        self._children: list[tuple[Gtk.Widget, float]] = []
        self.set_vexpand(True)

    def add(self, child: Gtk.Widget, weight: float | None = None) -> None:
        """``weight`` None = kein Anteil gesetzt: dann wie Gtk.Box (Minimum
        plus gleicher Anteil am Rest), sobald ein Kind einen Anteil hat,
        zaehlen die Anteile fuer alle."""
        self._children.append((child, None if weight is None else max(0.01, float(weight))))
        child.set_parent(self)

    def remove(self, child: Gtk.Widget) -> None:
        """Wie Gtk.Box.remove — apply_layout() holt so wiederverwendete Module heraus."""
        self._children = [(c, w) for c, w in self._children if c is not child]
        if child.get_parent() is self:
            child.unparent()
        self.queue_resize()

    def do_get_request_mode(self):  # type: ignore[override]
        # Hoehe haengt von der Breite ab (umbrechende Deck-Labels, Zeilen).
        # Ohne das misst Gtk.Grid die Hoehe fuer die *Mindest*breite, dort
        # brauchen die Labels mehr Zeilen, und die Spalte wurde 689 statt
        # 653 px hoch — hoeher als der Streifen.
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):  # type: ignore[override]
        if not self._children:
            return (0, 0, -1, -1)
        if orientation == Gtk.Orientation.HORIZONTAL:
            mins = [c.measure(orientation, -1)[0] for c, _ in self._children]
            nats = [c.measure(orientation, -1)[1] for c, _ in self._children]
            return (max(mins), max(nats), -1, -1)
        gaps = self._spacing * (len(self._children) - 1)
        mins = [c.measure(orientation, for_size)[0] for c, _ in self._children]
        nats = [c.measure(orientation, for_size)[1] for c, _ in self._children]
        return (sum(mins) + gaps, sum(nats) + gaps, -1, -1)

    def do_size_allocate(self, width: int, height: int, baseline: int):  # type: ignore[override]
        n = len(self._children)
        if not n:
            return
        avail = max(0, height - self._spacing * (n - 1))
        mins = [c.measure(Gtk.Orientation.VERTICAL, width)[0] for c, _ in self._children]
        if all(w is None for _, w in self._children):
            # Ohne Anteile wie eine Box: jedes Kind sein Minimum, dann wird
            # der Rest erst bis zur natuerlichen Hoehe aufgefuellt (anteilig
            # am Bedarf) und was dann noch bleibt gleich verteilt. So sieht
            # ein Layout ohne "height" aus wie vor der Einfuehrung der Anteile:
            # die Prozessliste bekommt ihre 14 Zeilen, Audio den Rest.
            nats = [c.measure(Gtk.Orientation.VERTICAL, width)[1] for c, _ in self._children]
            heights = list(map(float, mins))
            extra = max(0.0, avail - sum(mins))
            wants = [max(0, nt - m) for nt, m in zip(nats, mins)]
            want_total = sum(wants)
            if want_total > 0:
                fill = min(extra, want_total)
                heights = [h + fill * w / want_total for h, w in zip(heights, wants)]
                extra -= fill
            heights = [h + extra / n for h in heights]
            y = 0
            for (child, _), h in zip(self._children, heights):
                h = int(round(h))
                child.allocate(width, h, -1, Gsk.Transform.new().translate(Graphene.Point().init(0, y)))
                y += h + self._spacing
            return
        weights = [w if w is not None else 100.0 / n for _, w in self._children]
        total_w = sum(weights)
        heights = [avail * w / total_w for w in weights]
        # Kinder, die unter ihr Minimum fielen, auf das Minimum heben und den
        # Rest anteilig auf die uebrigen verteilen.
        fixed = set()
        for _ in range(n):
            over = [i for i in range(n) if i not in fixed and heights[i] < mins[i]]
            if not over:
                break
            for i in over:
                heights[i] = mins[i]
                fixed.add(i)
            rest = avail - sum(heights[i] for i in fixed)
            free_w = sum(weights[i] for i in range(n) if i not in fixed)
            for i in range(n):
                if i not in fixed:
                    heights[i] = max(0.0, rest * weights[i] / free_w) if free_w else 0.0
        y = 0
        for (child, _), h in zip(self._children, heights):
            h = int(round(h))
            # Position ueber eine Translation, wie GTK selbst es fuer Kinder tut.
            child.allocate(width, h, -1, Gsk.Transform.new().translate(Graphene.Point().init(0, y)))
            y += h + self._spacing

    def do_dispose(self):  # type: ignore[override]
        for child, _ in getattr(self, "_children", []):
            child.unparent()
        self._children = []
        Gtk.Widget.do_dispose(self)
