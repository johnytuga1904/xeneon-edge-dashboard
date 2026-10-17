"""MPRIS: was gerade spielt, und die Tasten dazu.

MPRIS ist der D-Bus-Standard, den unter Linux praktisch jeder Player bedient —
Spotify, YouTube im Browser, mpv, VLC, Rhythmbox. Ein Modul dagegen zu bauen
heisst, alle auf einmal zu bedienen, statt sich auf einen festzulegen.

Hier steht nur der D-Bus-Teil: ohne GTK, damit er ohne Fenster zu testen ist.
Das Widget liegt in ui/mediaplayer.py.

Gelesen wird ereignisgesteuert. ``PropertiesChanged`` meldet Titelwechsel und
Play/Pause von selbst; nur die Abspielposition muss abgefragt werden, weil
MPRIS sie nicht meldet (``Seeked`` kommt nur beim Springen). Das kostet einen
D-Bus-Aufruf pro Sekunde und nur, solange etwas laeuft.

Was ein Player meldet, ist nicht immer, was er tut. Brave (Chromium) meldet
"Paused" mit eingefrorener Position, waehrend YouTube hoerbar weiterlaeuft —
gesehen am 12.09.2026, Ton per PipeWire-Mitschnitt nachgewiesen. Dann stehen
zwei Browser mit "Paused" auf dem Bus, und der erste in der Liste gewinnt die
Anzeige, obwohl der andere spielt. Deshalb zaehlt im Zweifel der Sound-Server:
wessen Ausgabestrom laeuft, der spielt (``audible``, ueber sensors/audio.py).
"""
from __future__ import annotations
from dataclasses import dataclass
import threading
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import audio as audio_mod

BUS_PREFIX = "org.mpris.MediaPlayer2."
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
ROOT_IFACE = "org.mpris.MediaPlayer2"

# Ein Player, der nicht antwortet, darf die Oberflaeche nicht anhalten. Eine
# halbe Sekunde ist grosszuegig fuer einen lokalen Bus-Aufruf.
CALL_TIMEOUT_MS = 500

# Live-Streams melden als Laenge den groessten int64. Alles jenseits eines
# Tages ist "keine sinnvolle Dauer" — dann gibt es keinen Fortschritt.
MAX_SANE_LENGTH_US = 24 * 60 * 60 * 1_000_000

# Wie lange die Antwort des Sound-Servers gilt. Das Widget fragt im
# Sekundentakt nach; die Probe hoert jeden offenen Strom ~120 ms mit — alle
# drei Sekunden ist genau genug fuer "spielt noch / spielt nicht mehr".
AUDIBLE_CACHE_S = 3.0

# Wie viele Eltern nach oben zwischen dem Prozess, der den Ton haelt, und dem
# Player-Prozess liegen duerfen. Chromium: Audio-Dienst → Browser, eine Stufe;
# Firefox haelt ihn selbst. Mehr als ein paar gibt es nicht.
MAX_PARENT_HOPS = 6


@dataclass
class Track:
    """Was das Widget zum Zeichnen braucht. Leer = kein Player da."""

    player: str = ""          # Bus-Name, z.B. org.mpris.MediaPlayer2.spotify
    identity: str = ""        # Klarname, z.B. "Spotify"
    title: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""
    status: str = "Stopped"   # Playing | Paused | Stopped
    length_us: int = 0        # 0 = unbekannt oder Live-Stream
    position_us: int = 0
    can_next: bool = False
    can_prev: bool = False
    can_pause: bool = False
    can_play: bool = False
    # "Playing" stammt nicht vom Player, sondern vom Sound-Server: der Player
    # sagt Paused, sein Ton laeuft aber. Die Position ist dann eingefroren.
    inferred: bool = False

    @property
    def playing(self) -> bool:
        return self.status == "Playing"

    @property
    def present(self) -> bool:
        return bool(self.player)

    @property
    def fraction(self) -> float:
        """Fortschritt 0..1, oder 0 wenn es keine sinnvolle Dauer gibt."""
        if self.length_us <= 0:
            return 0.0
        return max(0.0, min(1.0, self.position_us / self.length_us))


def _first_artist(value) -> str:
    """``xesam:artist`` ist eine Liste; manche Player schicken einen String."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return str(value or "")


def _sane_length(value) -> int:
    try:
        length = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return length if 0 < length < MAX_SANE_LENGTH_US else 0


def _parent_pid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _descends_from(pid: int, ancestor: int) -> bool:
    """Ob ``ancestor`` in der Elternkette von ``pid`` liegt (oder es selbst ist)."""
    for _ in range(MAX_PARENT_HOPS):
        if pid <= 1:
            return False
        if pid == ancestor:
            return True
        pid = _parent_pid(pid)
    return False


class MprisWatcher:
    """Verfolgt die MPRIS-Player auf der Sitzungs-Bus und meldet Aenderungen.

    ``on_change`` wird gerufen, wenn sich etwas geaendert hat, das man sehen
    kann — nicht fuer die Position, die holt sich das Widget im Sekundentakt
    selbst ab.
    """

    def __init__(self, preferred: str = "", on_change=None):
        # Leer = automatisch: der Player, der gerade spielt. Sonst ein
        # Namensteil, z.B. "spotify".
        self.preferred = str(preferred or "").strip().lower()
        self._on_change = on_change
        self._bus: Gio.DBusConnection | None = None
        self._subs: list[int] = []
        self._names: list[str] = []
        self._pids: dict[str, int] = {}          # Bus-Name → PID des Players
        # Ergebnis der letzten Pegelprobe; die Probe selbst laeuft in einem
        # Thread, weil sie bis zu einer Sekunde je Strom blockieren kann.
        self._audible_at = 0.0
        self._audible_pids: set[int] = set()
        self._probe: threading.Thread | None = None

    # ----- Leben -----

    def start(self) -> None:
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            print(f"[xeneon-edge] MPRIS: keine Sitzungs-Bus ({e.message})")
            return
        self._scan()
        # Ein Abonnement fuer alle Player statt eines pro Player: der Pfad ist
        # bei allen derselbe, und wer neu dazukommt, ist ohne Zutun dabei.
        self._subs.append(self._bus.signal_subscribe(
            None, "org.freedesktop.DBus.Properties", "PropertiesChanged",
            OBJECT_PATH, None, Gio.DBusSignalFlags.NONE, self._on_props))
        self._subs.append(self._bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._on_name))

    def stop(self) -> None:
        if self._bus is not None:
            for sub in self._subs:
                self._bus.signal_unsubscribe(sub)
        self._subs = []
        self._bus = None

    # ----- Signale -----

    def _on_props(self, _c, sender, _p, _i, _s, params) -> None:
        # sender ist der eindeutige Name (":1.200"), nicht der MPRIS-Name —
        # deshalb nicht filtern, sondern einfach neu zeichnen lassen.
        self._notify()

    def _on_name(self, _c, _sender, _p, _i, _s, params) -> None:
        try:
            name = params.unpack()[0]
        except Exception:
            return
        if name.startswith(BUS_PREFIX):
            self._scan()
            self._notify()

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception as e:
                print(f"[xeneon-edge] MPRIS: on_change: {e}")

    def _scan(self) -> None:
        self._names = [n for n in self._list_names() if n.startswith(BUS_PREFIX)]
        # Ein Name kann nach einem Neustart des Players eine andere PID haben.
        self._pids = {n: pid for n, pid in self._pids.items() if n in self._names}

    def _list_names(self) -> list[str]:
        if self._bus is None:
            return []
        try:
            return self._bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                "ListNames", None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE,
                CALL_TIMEOUT_MS, None).unpack()[0]
        except GLib.Error:
            return []

    # ----- Abfragen -----

    def _get(self, name: str, iface: str, prop: str, default=None):
        if self._bus is None:
            return default
        try:
            return self._bus.call_sync(
                name, OBJECT_PATH, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (iface, prop)), GLib.VariantType("(v)"),
                Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None).unpack()[0]
        except GLib.Error:
            # Der Player kann zwischen zwei Aufrufen verschwinden, und
            # Eigenschaften wie Shuffle sind optional.
            return default

    def _pid(self, name: str) -> int:
        pid = self._pids.get(name)
        if pid is None:
            pid = 0
            if self._bus is not None:
                try:
                    pid = int(self._bus.call_sync(
                        "org.freedesktop.DBus", "/org/freedesktop/DBus",
                        "org.freedesktop.DBus", "GetConnectionUnixProcessID",
                        GLib.Variant("(s)", (name,)), GLib.VariantType("(u)"),
                        Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None).unpack()[0])
                except GLib.Error:
                    pid = 0
            self._pids[name] = pid
        return pid

    def audible(self, name: str) -> bool:
        """Ob der Prozess hinter ``name`` gerade Ton ausgibt — laut
        Sound-Server, nicht laut Player.

        Antwortet sofort mit dem letzten Messergebnis und stoesst bei Bedarf
        eine neue Probe an. Faellt die anders aus, kommt ``on_change`` — das
        Widget liest dann neu und bekommt die frische Antwort.
        """
        pid = self._pid(name)
        if not pid:
            return False
        self._maybe_probe()
        return any(_descends_from(p, pid) for p in self._audible_pids)

    def _maybe_probe(self) -> None:
        if self._probe is not None and self._probe.is_alive():
            return
        now = time.monotonic()
        if now - self._audible_at < AUDIBLE_CACHE_S:
            return
        self._audible_at = now
        self._probe = threading.Thread(target=self._probe_run, name="xeneon-mpris-probe",
                                       daemon=True)
        self._probe.start()

    def _probe_run(self) -> None:
        pids = audio_mod.audible_pids()

        def deliver() -> bool:
            # Zurueck auf dem GTK-Thread: hier darf der Zustand geschrieben
            # und das Widget angestossen werden.
            if pids != self._audible_pids:
                self._audible_pids = pids
                if self._bus is not None:      # nicht nach stop()
                    self._notify()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(deliver)

    def choose(self) -> str:
        """Welchen Player wir anzeigen.

        Ist ``preferred`` gesetzt, gilt *nur* dieser Player: laeuft er nicht,
        ist nichts anzuzeigen. Ersatzweise einen anderen zu nehmen waere eine
        Luege — wer "spotify" eintraegt, will nicht den YouTube-Tab sehen.

        Ohne Angabe der, der gerade spielt; sind mehrere offen (Browser-Tab
        und Spotify), ist der spielende gemeint. Sagt keiner "Playing", der,
        dessen Ton laeuft (siehe Modulkopf). Sonst der erste.
        """
        if not self._names:
            self._scan()
        if self.preferred:
            for name in self._names:
                if self.preferred in name.lower():
                    return name
            return ""
        for name in self._names:
            if self._get(name, PLAYER_IFACE, "PlaybackStatus") == "Playing":
                return name
        for name in self._names:
            if self.audible(name):
                return name
        return self._names[0] if self._names else ""

    def read(self) -> Track:
        name = self.choose()
        if not name:
            return Track()
        meta = self._get(name, PLAYER_IFACE, "Metadata", {}) or {}
        status = str(self._get(name, PLAYER_IFACE, "PlaybackStatus", "Stopped") or "Stopped")
        inferred = False
        if status != "Playing" and self.audible(name):
            # Der Player sagt Paused, sein Ton laeuft: anzeigen, was zu hoeren
            # ist. Die Position bleibt stehen, die kennt nur der Player.
            status, inferred = "Playing", True
        return Track(
            player=name,
            identity=str(self._get(name, ROOT_IFACE, "Identity", "") or ""),
            title=str(meta.get("xesam:title") or ""),
            artist=_first_artist(meta.get("xesam:artist")),
            album=str(meta.get("xesam:album") or ""),
            art_url=str(meta.get("mpris:artUrl") or ""),
            status=status,
            inferred=inferred,
            length_us=_sane_length(meta.get("mpris:length")),
            position_us=int(self._get(name, PLAYER_IFACE, "Position", 0) or 0),
            can_next=bool(self._get(name, PLAYER_IFACE, "CanGoNext", False)),
            can_prev=bool(self._get(name, PLAYER_IFACE, "CanGoPrevious", False)),
            can_pause=bool(self._get(name, PLAYER_IFACE, "CanPause", False)),
            can_play=bool(self._get(name, PLAYER_IFACE, "CanPlay", False)),
        )

    def position(self, name: str) -> int:
        """Nur die Position — das Einzige, was abgefragt werden muss."""
        return int(self._get(name, PLAYER_IFACE, "Position", 0) or 0)

    # ----- Steuern -----

    def call(self, name: str, method: str) -> None:
        """``PlayPause``, ``Next``, ``Previous`` — ohne Rueckmeldung.

        Was sich dadurch aendert, meldet der Player ohnehin ueber
        PropertiesChanged; auf die Antwort zu warten wuerde die Oberflaeche
        nur fuer die Dauer des Aufrufs anhalten.
        """
        if self._bus is None or not name:
            return
        self._bus.call(name, OBJECT_PATH, PLAYER_IFACE, method, None, None,
                       Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None, None)
