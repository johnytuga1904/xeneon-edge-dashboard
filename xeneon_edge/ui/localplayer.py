"""Musik aus einem Ordner, vom Dashboard selbst abgespielt.

Das Wiedergabe-Modul haengt sonst an MPRIS und zeigt nur, was ein *anderes*
Programm spielt. Auf dem Streifen ist aber oft gar kein Player offen — und
einen zu starten heisst, ihn auf dem Hauptmonitor zu bedienen. Deshalb dieser
kleine eigene Player: ein Ordner in den Einstellungen, und der Streifen spielt
ihn ohne fremdes Programm.

Abgespielt wird ueber GStreamer, mit einer Pipeline, die nur den Ton
dekodiert. Nicht ueber ``Gtk.MediaFile``: das ist dieselbe Maschinerie, aber
fuer Video gebaut — bei einem heruntergeladenen DJ-Set als ``.webm`` hat es
das 4K-Bild mitdekodiert, das nie jemand sieht, und dafuer dauerhaft einen
Kern belegt (nachgemessen: 70 % gegen 1 % mit der Audio-Pipeline). Deshalb
zaehlen hier auch Video-Container als Titel: Musik liegt oft als Video vor.
Keine neue Abhaengigkeit: wer GTK4 hat, hat in aller Regel auch
``gst-plugins-base`` und ``-good``. Fehlt etwas, wird das erkannt und
gemeldet, statt stumm nichts zu tun.

Titel und Kuenstler kommen aus dem Dateinamen und dem Ordner darueber, nicht
aus den Tags: Tags zu lesen hiesse, GStreamers Discoverer (oder mutagen)
dazuzunehmen, und dafuer ist der Gewinn zu klein — Musikordner sind
ueblicherweise ``Kuenstler/Album/01 Titel.flac``.

Hier steht kein GTK-Widget, nur Wiedergabe und Liste; das Widget liegt in
ui/mediaplayer.py.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

import gi
from gi.repository import Gio, GLib  # noqa: E402

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst  # noqa: E402
except (ValueError, ImportError):
    # Typelib fehlt (Debian: gir1.2-gstreamer-1.0). Der Player meldet das
    # beim ersten Start statt beim Import — das Modul soll trotzdem bauen.
    Gst = None

# Was gaengige Sammlungen enthalten. Alles davon spielt GStreamer mit den
# Basis-Plugins; exotischere Formate schaden nicht, sie werden beim Abspielen
# einfach uebersprungen.
AUDIO_SUFFIXES = frozenset({
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac",
    ".wav", ".wma", ".mpc", ".ape", ".alac", ".aiff",
})
# Video-Container zaehlen mit — gespielt wird nur ihre Tonspur. Ein
# heruntergeladenes Konzert ist Musik, auch wenn ein Bild dabeiliegt.
VIDEO_SUFFIXES = frozenset({".webm", ".mp4", ".m4v", ".mkv", ".mov", ".ogv"})
MEDIA_SUFFIXES = AUDIO_SUFFIXES | VIDEO_SUFFIXES

# Die Pipeline. ``caps=audio/x-raw`` haelt decodebin beim Ton an, und ohne
# ``expose-all-streams`` wirft es die Videospur weg, statt sie zu dekodieren
# und ins Leere zu schicken. Elemente aus gst-plugins-base (uridecodebin,
# audioconvert, audioresample) und -good (autoaudiosink → pulsesink).
_PIPELINE = ("uridecodebin name=src caps=audio/x-raw expose-all-streams=false "
             "! audioconvert ! audioresample ! autoaudiosink")

# yt-dlp haengt die Video-ID an: "Titel [dQw4w9WgXcQ].webm". Elf Zeichen aus
# Buchstaben, Ziffern, - und _ in eckigen Klammern am Ende — die gehoeren
# nicht in die Anzeige.
_YT_ID = re.compile(r"\s*\[[A-Za-z0-9_-]{11}\]$")

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
                 if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES]
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


def _backend_error() -> str:
    """Leer, wenn GStreamer samt der noetigen Elemente da ist — sonst der
    Grund, wie er ins Journal gehoert."""
    if Gst is None:
        return ("GStreamer-Bindings fehlen (Debian: gir1.2-gstreamer-1.0, "
                "Fedora: python3-gstreamer1)")
    if not Gst.is_initialized():
        ok, _argv = Gst.init_check(None)
        if not ok:
            return "GStreamer laesst sich nicht initialisieren"
    missing = [name for name in ("uridecodebin", "audioconvert", "audioresample",
                                 "autoaudiosink")
               if Gst.ElementFactory.find(name) is None]
    if missing:
        return (f"GStreamer-Elemente fehlen: {', '.join(missing)} — "
                "gst-plugins-base und gst-plugins-good installieren")
    return ""


class LocalPlayer:
    """Playlist aus einem Ordner, abgespielt ueber eine GStreamer-Pipeline.

    ``on_change`` meldet, dass sich etwas Sichtbares geaendert hat (Titel,
    Play/Pause) — dieselbe Rolle wie bei ``MprisWatcher``, damit das Widget
    beide Quellen gleich behandeln kann.
    """

    def __init__(self, folder: str, shuffle: bool = False, on_change=None) -> None:
        self.folder = Path(folder).expanduser() if folder else None
        self.shuffle = bool(shuffle)
        self._on_change = on_change
        self._pipeline = None   # Gst.Pipeline, solange ein Titel geladen ist
        self._bus = None
        self._playing = False   # unsere Absicht; Gst wechselt asynchron
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
        return self._pipeline is not None and self.current is not None

    @property
    def playing(self) -> bool:
        return self._pipeline is not None and self._playing

    @property
    def title(self) -> str:
        track = self.current
        return _YT_ID.sub("", track.stem) if track is not None else ""

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

    def _query(self, what) -> int:
        """Dauer oder Position in Mikrosekunden; 0, solange Gst sie nicht
        kennt (die ersten Millisekunden nach dem Laden, oder Streams ohne
        Laenge)."""
        if self._pipeline is None:
            return 0
        ok, value = what(Gst.Format.TIME)
        return int(value) // 1000 if ok and value >= 0 else 0

    @property
    def length_us(self) -> int:
        return self._query(self._pipeline.query_duration) if self._pipeline else 0

    @property
    def position_us(self) -> int:
        return self._query(self._pipeline.query_position) if self._pipeline else 0

    @property
    def label(self) -> str:
        """Was in der Kopfzeile steht, wo sonst der Playername steht."""
        if self.folder is None:
            return ""
        if not self.files:
            return f"{self.folder.name} — empty"
        return f"{self.folder.name} · {self._pos + 1}/{len(self.files)}"

    # ----- Steuerung -----

    def play_pause(self) -> None:
        if self._pipeline is None:
            self._start(0)
            return
        self._playing = not self._playing
        self._pipeline.set_state(Gst.State.PLAYING if self._playing
                                 else Gst.State.PAUSED)
        self._notify()

    def next(self) -> None:
        self._start(self._pos + 1)

    def previous(self) -> None:
        # Wie bei jedem Player: mitten im Titel springt "zurueck" an den
        # Anfang, erst gleich danach zum vorherigen Titel.
        if self._pipeline is not None and self.position_us > 3_000_000:
            self._pipeline.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
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
        # Vor dem ersten Titel pruefen, nicht erst am Fehler: sonst liefe der
        # Player durch alle Titel, jeder mit einem Fehler im Log.
        problem = _backend_error()
        if problem:
            self.available = False
            print(f"[xeneon-edge] Musikordner: {problem}")
            self._pos = -1
            self._notify()
            return
        try:
            pipeline = Gst.parse_launch(_PIPELINE)
        except GLib.Error as e:
            self.available = False
            print(f"[xeneon-edge] Musikordner: Pipeline baut nicht ({e.message})")
            self._pos = -1
            self._notify()
            return
        pipeline.get_by_name("src").set_property(
            "uri", Gio.File.new_for_path(str(track)).get_uri())
        # Die Bus-Nachrichten kommen auf dem GLib-Main-Loop an, also auf dem
        # GTK-Thread — die Callbacks duerfen direkt an das Widget melden.
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)
        self._pipeline, self._bus = pipeline, bus
        self._playing = True
        pipeline.set_state(Gst.State.PLAYING)
        self._notify()

    def _on_eos(self, _bus, _msg) -> None:
        # Nicht aus der Nachricht heraus die naechste Datei laden: die
        # Pipeline wird im Callback noch gebraucht.
        GLib.idle_add(self._advance)

    def _advance(self) -> bool:
        self.next()
        return GLib.SOURCE_REMOVE

    def _on_error(self, _bus, msg) -> None:
        error, _debug = msg.parse_error()
        track = self.current
        print(f"[xeneon-edge] Titel nicht abspielbar ({track.name if track else '?'}): "
              f"{error.message}")
        GLib.idle_add(self._advance)

    def _drop_media(self) -> None:
        if self._pipeline is None:
            return
        self._bus.remove_signal_watch()
        self._pipeline.set_state(Gst.State.NULL)
        self._pipeline, self._bus = None, None
        self._playing = False

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def close(self) -> None:
        self._drop_media()
