"""Notizen: eine Datei anzeigen, mit dem Finger scrollen, eine Zeile kopieren.

Lesend, mit Absicht. Am Streifen haengt keine Tastatur, ein Texteditor dort
waere Theater. Das Modul zeigt eine Text-, Markdown- oder JSON-Datei und laedt
sie neu, wenn sie sich aendert — geschrieben wird sie woanders, auf dem
Rechner mit Tastatur.

Bedient wird mit dem Finger: der Streifen ist ein Touchscreen, und die Maus
kommt dort schlecht hin. Deshalb eine Gtk.ListBox in einem
Gtk.ScrolledWindow — die kann GTK von Haus aus kinetisch scrollen — und jede
Zeile ist eine Zeile der Liste. Ein Tipp darauf legt sie in die
Zwischenablage; ohne Tastatur ist das der einzige Weg, etwas aus der Datei
herauszubekommen.

Markdown wird nicht formatiert. Eine ``.md``-Datei ist als Klartext lesbar,
und ein halb umgesetztes Markdown (Ueberschriften ja, Tabellen nein) ist
verwirrender als gar keines.
"""
from __future__ import annotations
import json
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib  # noqa: E402

# Obergrenze fuer die Zeilen in der Liste. Eine ListBox baut pro Zeile ein
# Widget; bei einer Logdatei mit 200'000 Zeilen dauert das Minuten und der
# Speicher waere weg. Was darueber liegt, gehoert nicht auf einen Streifen.
MAX_LINES = 1500

# Datei-Ereignisse kommen in Schueben: ein Editor schreibt truncate, write,
# rename, und jeder Schritt loest aus. Einmal neu lesen reicht.
RELOAD_DEBOUNCE_MS = 250

# So lange steht "kopiert" im Kopf des Panels.
COPIED_HINT_MS = 1500

# Ab hier wird der Dateiname im Panelkopf gekuerzt.
TITLE_CHARS = 28


def _shorten(name: str) -> str:
    """Langen Dateinamen von vorn kuerzen — hinten steht die Endung."""
    return name if len(name) <= TITLE_CHARS else "…" + name[-(TITLE_CHARS - 1):]


def _render(path: Path) -> tuple[list[str], str]:
    """Dateiinhalt als Zeilen, plus eine Statuszeile fuer den Panelkopf.

    JSON wird eingerueckt: eine einzeilige API-Antwort waere sonst eine
    einzige, nicht lesbare Zeile. Ist sie kaputt, bleibt sie, wie sie ist —
    dann will man ja gerade sehen, was drinsteht.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [], f"not readable: {e.strerror or e}"

    if path.suffix.lower() == ".json":
        try:
            raw = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except (ValueError, RecursionError):
            pass

    lines = raw.splitlines()
    if len(lines) > MAX_LINES:
        rest = len(lines) - MAX_LINES
        return lines[:MAX_LINES] + [f"… {rest} more lines"], f"{len(lines)} lines"
    return lines, f"{len(lines)} lines"


class NotesModule(Gtk.Box):
    __gtype_name__ = "XeNotesModule"

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.add_css_class("panel")
        self.add_css_class("notes-module")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.needs = frozenset()

        raw_path = str(config.get("path") or "").strip()
        self._path = Path(raw_path).expanduser() if raw_path else None
        self._monitor: Gio.FileMonitor | None = None
        self._reload_source = 0
        self._hint_source = 0
        self._status_text = ""

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class("panel-header")
        # Gekuerzt wird der Text, nicht das Label: ".panel-label" traegt
        # letter-spacing, und Pango rechnet den Abstand hinter dem letzten
        # Zeichen nicht in die natuerliche Breite ein. Mit set_ellipsize()
        # schneidet GTK deshalb ab, obwohl die Zeile passt — aus
        # "notizen.md" wurde "notizen.…".
        title = Gtk.Label(label=_shorten(self._path.name) if self._path else "Notes",
                          xalign=0)
        title.add_css_class("panel-label")
        self.status = Gtk.Label(label="", xalign=1)
        self.status.add_css_class("panel-sublabel")
        self.status.set_hexpand(True)
        self.status.set_ellipsize(3)
        header.append(title)
        header.append(self.status)
        self.append(header)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list.add_css_class("notes-list")
        self.list.connect("row-activated", self._on_row)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.list)
        scroller.set_vexpand(True)
        self.append(scroller)

        self._load()
        self._watch()

    # ----- Datei -----

    def _watch(self) -> None:
        if self._path is None:
            return
        try:
            gfile = Gio.File.new_for_path(str(self._path))
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_changed)
        except GLib.Error as e:
            # Kein Grund, das Modul aufzugeben: der Inhalt steht ja schon da,
            # er aktualisiert sich nur nicht mehr von selbst.
            print(f"[xeneon-edge] Notizen: kann {self._path} nicht beobachten: {e.message}")

    def _on_changed(self, *_args) -> None:
        if self._reload_source:
            GLib.source_remove(self._reload_source)
        self._reload_source = GLib.timeout_add(RELOAD_DEBOUNCE_MS, self._reload)

    def _reload(self) -> bool:
        self._reload_source = 0
        self._load()
        return GLib.SOURCE_REMOVE

    def _load(self) -> None:
        child = self.list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.list.remove(child)
            child = nxt

        if self._path is None:
            self._add_row("No file chosen — in the editor, pick a text, Markdown "
                          "or JSON file under \"File\".", plain=True)
            self._set_status("")
            return
        if not self._path.exists():
            self._add_row(f"Not found: {self._path}", plain=True)
            self._set_status("missing")
            return

        lines, status = _render(self._path)
        self._set_status(status)
        if not lines:
            self._add_row("(empty)", plain=True)
            return
        for line in lines:
            self._add_row(line)

    def _set_status(self, text: str) -> None:
        """Statuszeile setzen und merken — _clear_hint stellt sie wieder her."""
        self._status_text = text
        self.status.set_label(text)

    def _add_row(self, text: str, plain: bool = False) -> None:
        row = Gtk.ListBoxRow()
        # Leerzeilen und Hinweise sind nichts zum Kopieren — nicht anklickbar,
        # damit ein Tipp daneben nicht die Zwischenablage leert.
        row.set_activatable(not plain and bool(text.strip()))
        label = Gtk.Label(label=text or " ", xalign=0)
        label.add_css_class("notes-line")
        if plain:
            label.add_css_class("notes-hint")
            label.set_wrap(True)
        else:
            label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        row.set_child(label)
        self.list.append(row)

    # ----- Kopieren -----

    def _on_row(self, _list, row: Gtk.ListBoxRow) -> None:
        label = row.get_child()
        if not isinstance(label, Gtk.Label):
            return
        text = label.get_label()
        if not self._copy(text):
            return
        row.add_css_class("copied")
        self.status.set_label("copied")
        if self._hint_source:
            GLib.source_remove(self._hint_source)
        self._hint_source = GLib.timeout_add(COPIED_HINT_MS, self._clear_hint, row)

    def _copy(self, text: str) -> bool:
        display = Gdk.Display.get_default()
        if display is None:
            return False
        clipboard = display.get_clipboard()
        try:
            clipboard.set(text)
        except Exception:
            # Aeltere Bindings kennen set() nicht mit einem nackten String.
            try:
                clipboard.set_content(Gdk.ContentProvider.new_for_value(text))
            except Exception as e:
                print(f"[xeneon-edge] Notizen: Kopieren fehlgeschlagen: {e}")
                return False
        return True

    def _clear_hint(self, row: Gtk.ListBoxRow) -> bool:
        self._hint_source = 0
        row.remove_css_class("copied")
        # Den gemerkten Text setzen, nicht die Datei neu lesen: bei 1500
        # Zeilen mit JSON-Einrueckung waere das ein spuerbarer Aufwand,
        # nur um wieder "1500 Zeilen" hinzuschreiben.
        self.status.set_label(self._status_text)
        return GLib.SOURCE_REMOVE

    # ----- Fenster-Schnittstelle -----

    def update(self, snap) -> None:
        """Der Inhalt kommt aus der Datei, nicht aus dem Snapshot."""

    def do_dispose(self):  # type: ignore[override]
        # Der FileMonitor haelt eine Referenz auf diese Instanz. Ohne
        # Abbestellen bliebe sie samt Zeilen am Leben, wenn das Layout das
        # Modul entfernt.
        for source in (self._reload_source, self._hint_source):
            if source:
                GLib.source_remove(source)
        self._reload_source = self._hint_source = 0
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        Gtk.Box.do_dispose(self)
