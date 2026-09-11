"""Musik aus einem Ordner, vom Dashboard selbst abgespielt.

Das Wiedergabe-Modul haengt sonst an MPRIS und zeigt nur, was ein *anderes*
Programm spielt. Auf dem Streifen ist aber oft gar kein Player offen — und
einen zu starten heisst, ihn auf dem Hauptmonitor zu bedienen. Deshalb dieser
kleine eigene Player: ein Ordner in den Einstellungen, und der Streifen spielt
ihn ohne fremdes Programm.

Abgespielt wird ueber ``Gtk.MediaFile``, also GStreamer — dieselbe Maschinerie,
die GTK fuer jedes Video benutzt. Keine neue Abhaengigkeit: wer GTK4 hat, hat
in aller Regel auch ``gst-plugins-base`` und ``-good``. Fehlt das Backend,
liefert GTK ein ``GtkNoMediaFile``; das wird erkannt und gemeldet, statt
stumm nichts zu tun.

Titel und Kuenstler kommen aus dem Dateinamen und dem Ordner darueber, nicht
aus den Tags: Tags zu lesen hiesse, GStreamers Discoverer (oder mutagen)
dazuzunehmen, und dafuer ist der Gewinn zu klein — Musikordner sind
ueblicherweise ``Kuenstler/Album/01 Titel.flac``.

Hier steht kein GTK-Widget, nur Wiedergabe und Liste; das Widget liegt in
ui/mediaplayer.py.
"""
from __future__ import annotations

import random
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib, GObject  # noqa: E402

# GType-Namen des Platzhalters, den Gtk.MediaFile ohne Media-Backend liefert.
_NO_BACKEND_TYPES = ("GtkNoMediaFile", "GtkNothingMedia")

# Was gaengige Sammlungen enthalten. Alles davon spielt GStreamer mit den
# Basis-Plugins; exotischere Formate schaden nicht, sie werden beim Abspielen
# einfach uebersprungen.
AUDIO_SUFFIXES = frozenset({
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac",
    ".wav", ".wma", ".mpc", ".ape", ".alac", ".aiff",
})

# Deckel gegen einen versehentlich gewaehlten Ordner mit dem halben Home
# darin. Wer mehr Titel hat, bekommt die ersten 5000 in Sortierreihenfolge.
MAX_TRACKS = 5000

# Dateinamen, die ueblicherweise das Albumcover sind.
COVER_NAMES = ("cover", "folder", "front", "album", "albumart")
COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def scan(folder: Path) -> list[Path]:
    """Audiodateien unter ``folder``, sortiert wie im Dateimanager.

    Rekursiv, weil eine Sammlung nach Kuenstler und Album verschachtelt ist —
    ein nicht-rekursiver Scan faende in so einem Ordner keine einzige Datei.
    """
    try:
        found = [p for p in folder.rglob("*")
                 if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES]
    except OSError as e:
        print(f"[xeneon-edge] Musikordner nicht lesbar: {e}")
        return []
    found.sort(key=lambda p: tuple(part.lower() for part in p.parts))
    if len(found) > MAX_TRACKS:
        print(f"[xeneon-edge] Musikordner hat {len(found)} Titel — "
              f"es werden die ersten {MAX_TRACKS} genommen")
        del found[MAX_TRACKS:]
    return found


def find_cover(track: Path) -> str:
    """file://-Adresse eines Covers neben der Datei, sonst leer."""
    try:
        entries = {p.name.lower(): p for p in track.parent.iterdir() if p.is_file()}
    except OSError:
        return ""
    for name in COVER_NAMES:
        for suffix in COVER_SUFFIXES:
            hit = entries.get(name + suffix)
            if hit is not None:
                return Gio.File.new_for_path(str(hit)).get_uri()
    return ""


class LocalPlayer:
    """Playlist aus einem Ordner, abgespielt mit ``Gtk.MediaFile``.

    ``on_change`` meldet, dass sich etwas Sichtbares geaendert hat (Titel,
    Play/Pause) — dieselbe Rolle wie bei ``MprisWatcher``, damit das Widget
    beide Quellen gleich behandeln kann.
    """

    def __init__(self, folder: str, shuffle: bool = False, on_change=None) -> None:
        self.folder = Path(folder).expanduser() if folder else None
        self.shuffle = bool(shuffle)
        self._on_change = on_change
        self._media: Gtk.MediaStream | None = None
        self._order: list[int] = []
        self._pos = -1          # Index in _order, nicht in files
        self.files: list[Path] = []
        self.available = True   # bis das Gegenteil bewiesen ist
        if self.folder is not None:
            self._rescan()

    # ----- Liste -----

    def _rescan(self) -> None:
        self.files = scan(self.folder) if self.folder is not None else []
        self._order = list(range(len(self.files)))
        if self.shuffle:
            random.shuffle(self._order)

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def current(self) -> Path | None:
        if 0 <= self._pos < len(self._order):
            return self.files[self._order[self._pos]]
        return None

    # ----- Zustand, wie ihn das Widget liest -----

    @property
    def active(self) -> bool:
        """Ein Titel ist geladen — laufend oder pausiert."""
        return self._media is not None and self.current is not None

    @property
    def playing(self) -> bool:
        return bool(self._media is not None and self._media.get_playing())

    @property
    def title(self) -> str:
        track = self.current
        return track.stem if track is not None else ""

    @property
    def artist(self) -> str:
        """Der Ordner ueber der Datei — bei ``Kuenstler/Album/Titel`` das Album."""
        track = self.current
        if track is None or self.folder is None:
            return ""
        parent = track.parent
        return "" if parent == self.folder else parent.name

    @property
    def art_url(self) -> str:
        track = self.current
        return find_cover(track) if track is not None else ""

    @property
    def length_us(self) -> int:
        return int(self._media.get_duration()) if self._media is not None else 0

    @property
    def position_us(self) -> int:
        return int(self._media.get_timestamp()) if self._media is not None else 0

    @property
    def label(self) -> str:
        """Was in der Kopfzeile steht, wo sonst der Playername steht."""
        if self.folder is None:
            return ""
        if not self.files:
            return f"{self.folder.name} — leer"
        return f"{self.folder.name} · {self._pos + 1}/{len(self.files)}"

    # ----- Steuerung -----

    def play_pause(self) -> None:
        if self._media is None:
            self._start(0)
            return
        self._media.set_playing(not self._media.get_playing())
        self._notify()

    def next(self) -> None:
        self._start(self._pos + 1)

    def previous(self) -> None:
        # Wie bei jedem Player: mitten im Titel springt "zurueck" an den
        # Anfang, erst gleich danach zum vorherigen Titel.
        if self._media is not None and self._media.get_timestamp() > 3_000_000:
            self._media.seek(0)
            self._notify()
            return
        self._start(self._pos - 1)

    def stop(self) -> None:
        self._drop_media()
        self._pos = -1
        self._notify()

    def _start(self, pos: int) -> None:
        """Titel an Position ``pos`` der Reihenfolge laden und abspielen."""
        if not self.files:
            self._rescan()          # Ordner kann inzwischen gefuellt sein
        if not self.files:
            self._notify()
            return
        # Am Ende der Liste ist Schluss statt Endlosschleife: das Modul faellt
        # danach zurueck auf das, was sonst auf dem Rechner spielt.
        if pos >= len(self._order):
            self._rescan()
            self.stop()
            return
        if pos < 0:
            pos = 0

        self._drop_media()
        self._pos = pos
        track = self.current
        if track is None:
            self._notify()
            return
        media = Gtk.MediaFile.new_for_file(Gio.File.new_for_path(str(track)))
        # GTK liefert ohne Backend ein GtkNoMediaFile (aeltere Versionen:
        # GtkNothingMedia). Davor die Instanz gebaut und erst am Fehlertext
        # gescheitert — der Player lief dann durch alle Titel, jeder mit
        # einem Fehler im Log.
        if GObject.type_name(media) in _NO_BACKEND_TYPES:
            self.available = False
            print("[xeneon-edge] Kein GTK-Media-Backend — fuer den Musikordner "
                  "fehlen gst-plugins-base und gst-plugins-good "
                  "(Debian: libgtk-4-media-gstreamer)")
            self._drop_media()
            self._pos = -1
            self._notify()
            return
        self._media = media
        media.connect("notify::ended", self._on_ended)
        media.connect("notify::error", self._on_error)
        media.connect("notify::playing", lambda *_a: self._notify())
        media.set_playing(True)
        self._notify()

    def _on_ended(self, media, _param) -> None:
        if media.get_ended():
            # Nicht aus dem Signal heraus die naechste Datei laden: GTK raeumt
            # den Stream gerade selbst auf.
            GLib.idle_add(self._advance)

    def _advance(self) -> bool:
        self.next()
        return GLib.SOURCE_REMOVE

    def _on_error(self, media, _param) -> None:
        error = media.get_error()
        if error is None:
            return
        track = self.current
        print(f"[xeneon-edge] Titel nicht abspielbar ({track.name if track else '?'}): "
              f"{error.message}")
        GLib.idle_add(self._advance)

    def _drop_media(self) -> None:
        if self._media is None:
            return
        self._media.set_playing(False)
        self._media = None

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def close(self) -> None:
        self._drop_media()
