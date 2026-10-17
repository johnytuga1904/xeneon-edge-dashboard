"""Launch deck: grid of buttons with hold-to-confirm for dangerous macros."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

from pathlib import Path
import re

from ..config_store import DECK_COLS, DECK_SLOTS
from ..launcher import launch as _launch
from .icons import resolve_icon


_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_PAD_CSS_PROVIDER: Gtk.CssProvider | None = None


def pad_colour(entry: dict) -> str | None:
    """'#rrggbb' aus dem accent-Feld, oder None fuer den Theme-Akzent."""
    m = _HEX.match(str(entry.get("accent") or "").strip())
    return m.group(1).lower() if m else None


def _apply_pad_colours(colours: set[str]) -> None:
    """Eine CSS-Regel pro benutzter Farbe: die untere Rahmenlinie des Pads.

    Ein Provider fuer alle Pads, bei jedem populate() neu geladen — die Menge
    der Farben ist klein und aendert sich nur, wenn der Editor speichert.
    Prioritaet ueber dem Stylesheet, damit die Farbe den @accent-Default aus
    style.css ueberstimmt.
    """
    global _PAD_CSS_PROVIDER
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _PAD_CSS_PROVIDER is None:
        _PAD_CSS_PROVIDER = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            display, _PAD_CSS_PROVIDER, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    css = "\n".join(
        f"button.deck-btn.pad-{c} {{ border-bottom-color: #{c}; }}"
        for c in sorted(colours))
    try:
        _PAD_CSS_PROVIDER.load_from_string(css)
    except Exception as e:  # pragma: no cover
        print(f"[xeneon-edge] pad colours: {e}")


def display_label(entry: dict) -> str:
    """Was auf dem Button steht.

    Faellt auf den Dateinamen des Kommandos zurueck, wenn kein Label gesetzt
    ist: ein Slot mit Kommando aber ohne Label sah sonst leer aus, loeste beim
    Antippen aber trotzdem aus. Leer bleibt nur, was wirklich unbelegt ist.
    """
    label = (entry.get("label") or "").strip()
    if label:
        return label
    cmd = (entry.get("command") or "").strip()
    if not cmd:
        return ""
    p = Path(cmd)
    return p.stem if p.suffix else p.name


class DeckButton(Gtk.Button):
    __gtype_name__ = "XeDeckButton"

    def __init__(self, entry: dict, *, hold_to_confirm: bool = True,
                 isolate: bool = True, slot: int | None = None,
                 monitor: str = ""):
        super().__init__()
        self._entry = entry
        self._isolate = isolate
        self._monitor = monitor
        self._slot = slot
        self._hold = bool(entry.get("confirm")) and hold_to_confirm
        self.add_css_class("deck-btn")
        if entry.get("kind") == "macro":
            self.add_css_class("macro")
        if entry.get("confirm"):
            self.add_css_class("danger")
        colour = pad_colour(entry)
        if colour:
            self.add_css_class(f"pad-{colour}")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        # Horizontal FILL, nicht CENTER: bei CENTER bekommt der Kasten nur
        # seine natural width, und die eines umbrechenden Labels mit
        # set_lines(2) ist die Breite fuer *zwei* Zeilen — also rund die
        # Haelfte. "Editor" wurden so 33px zugeteilt, obwohl der Button 130
        # breit ist, und der Name brach mitten im Wort um. Vertikal bleibt es
        # zentriert, und Icon wie Label zentrieren sich weiterhin selbst.
        body.set_halign(Gtk.Align.FILL)
        body.set_valign(Gtk.Align.CENTER)

        # Skip empty slots: keep the button visible but no icon/label clutter
        label_text = display_label(entry)
        if label_text:
            try:
                gicon = resolve_icon(entry)
                img = Gtk.Image.new_from_gicon(gicon)
                img.set_pixel_size(26)  # compact for 8-row deck on 720px display
                img.set_halign(Gtk.Align.CENTER)
                body.append(img)
            except Exception as e:  # pragma: no cover
                print(f"[xeneon-edge] icon resolve failed for {entry.get('id')}: {e}")

        lbl = Gtk.Label(label=label_text or "—")
        lbl.set_xalign(0.5)
        lbl.set_justify(Gtk.Justification.CENTER)
        # Zweizeilig umbrechen statt nach einer Zeile abzuschneiden — "qwen 96k
        # vision" passte sonst nie. WORD_CHAR bricht lange Script-Namen ohne
        # Leerzeichen notfalls mitten im Wort.
        #
        # Kein set_ellipsize dazu: GTK4 stuetzt die Kombination aus Wrap und
        # Ellipsize nicht, die Breitenverhandlung wird dann unvorhersehbar. Auf
        # dem Deck brach das kurze Namen mitten im Wort um ("Edito-r",
        # "File-s", "Screensho-t"), waehrend laengere daneben einzeilig blieben.
        # Die Mindestbreite bleibt auch ohne Ellipsize klein, weil WORD_CHAR
        # notfalls nach jedem Zeichen umbrechen darf — die Deck-Spalten werden
        # also weiterhin nicht auseinandergedrueckt.
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_lines(2)
        lbl.set_max_width_chars(16)
        # Die volle Buttonbreite nutzen statt der natural width (siehe body).
        lbl.set_halign(Gtk.Align.FILL)
        lbl.set_hexpand(True)
        lbl.add_css_class("deck-label")
        # Hold-to-confirm is signalled by the .danger CSS class on the button
        # (red border) — no extra "hold" sub-label, that pushes the deck taller
        # than the 660px Xeneon Edge content area.
        body.append(lbl)
        self.set_child(body)

        if self._hold:
            # Etwa 1 s halten: der Faktor multipliziert gtk-long-press-time
            # (Standard 500 ms). 0.6 waren nur 300 ms — kaum laenger als ein
            # Tipper, fuer poweroff/reboot zu wenig.
            gesture = Gtk.GestureLongPress.new()
            gesture.set_delay_factor(2.0)
            gesture.connect("pressed", self._on_long_pressed)
            self.add_controller(gesture)
            # eat regular clicks (we still need a clicked-handler so GTK doesn't
            # complain, but it does nothing for hold-buttons)
            self.connect("clicked", lambda *_: None)
        else:
            self.connect("clicked", lambda *_: self._fire())

    def _fire(self) -> None:
        _launch(self._entry, isolate=self._isolate, slot=self._slot,
                monitor=self._monitor)

    def _on_long_pressed(self, _gesture, _x, _y) -> None:
        # animate confirm flash, then launch
        self.add_css_class("hot")
        GLib.timeout_add(180, self._fire_and_clear)

    def _fire_and_clear(self) -> bool:
        self.remove_css_class("hot")
        self._fire()
        return False


class LaunchDeck(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("panel")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Launch Deck", xalign=0); title.add_css_class("panel-label")
        sub = Gtk.Label(label="Apps · Macros", xalign=1); sub.add_css_class("panel-sublabel")
        sub.set_hexpand(True)
        head.append(title); head.append(sub)
        self.append(head)

        self.grid = Gtk.Grid(row_spacing=3, column_spacing=3)
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_homogeneous(True)
        self.grid.set_hexpand(True)
        self.grid.set_vexpand(True)
        self.append(self.grid)

    def populate(self, apps: list[dict], macros: list[dict], *,
                 hold_to_confirm: bool, isolate: bool = True,
                 app_slots: int = 9, monitor: str = "") -> None:
        # clear
        child = self.grid.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt

        # DECK_SLOTS Plaetze, zeilenweise gefuellt: erst `app_slots` Apps, dann
        # Macros bis das Raster voll ist. Die Grenze liegt bewusst auf Slot- und
        # nicht auf Zeilenebene — bei app_slots=4 teilen sich Apps und Macros
        # eben Zeile 2. Unterscheidbar bleiben sie ueber die .macro-CSS-Klasse.
        app_slots = max(0, min(DECK_SLOTS, app_slots))
        # Auf app_slots auffuellen: sonst ruecken die Macros nach oben, sobald
        # die Apps-Liste kuerzer ist als ihr Kontingent, und die Positionen
        # verschieben sich unter dem Finger.
        head = list(apps[:app_slots]) + [{}] * max(0, app_slots - len(apps[:app_slots]))
        entries = head + list(macros[:DECK_SLOTS - app_slots])
        # Und hinten auffuellen, damit das Raster auch dann geschlossen wirkt,
        # wenn apps.json weniger Eintraege hat als das Deck Plaetze.
        entries += [{}] * max(0, DECK_SLOTS - len(entries))
        _apply_pad_colours({c for c in (pad_colour(e) for e in entries) if c})
        for i, entry in enumerate(entries[:DECK_SLOTS]):
            self.grid.attach(DeckButton(entry, hold_to_confirm=hold_to_confirm,
                                        isolate=isolate, slot=i,
                                        monitor=monitor),
                             i % DECK_COLS, i // DECK_COLS, 1, 1)
