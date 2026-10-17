"""PipeWire/PulseAudio control via pactl + wpctl."""
from __future__ import annotations
import os
import re
import select
import shutil
import struct
import subprocess
import threading
import time


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# Inherit the user's environment (XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS, …)
# but override locale so pactl emits English keys (Name:, Description:) for
# stable parsing on non-en_US systems.
_PACTL_ENV = {**os.environ, "LANG": "C", "LC_ALL": "C", "LANGUAGE": "C"}


def _run(cmd: list[str], timeout: float = 1.5) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False, env=_PACTL_ENV)
        return proc.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _list_short(kind: str) -> list[dict]:
    # `pactl list short sinks` → "<id>\t<name>\t<driver>\t<spec>\t<state>"
    out: list[dict] = []
    for line in _run(["pactl", "list", "short", kind]).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        out.append({"id": parts[1], "name": parts[1]})
    return out


def _description_map(kind: str) -> dict[str, str]:
    """Pretty descriptions parsed from `pactl list <kind>` (verbose)."""
    text = _run(["pactl", "list", kind])
    descs: dict[str, str] = {}
    current_name = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            current_name = s.split("Name:", 1)[1].strip()
        elif s.startswith("Description:") and current_name:
            descs[current_name] = s.split("Description:", 1)[1].strip()
            current_name = None
    return descs


def _default_name(kind: str) -> str | None:
    # kind: "sink" or "source"
    out = _run(["pactl", "get-default-" + kind]).strip()
    return out or None


def _volume_pct(kind: str, name: str) -> tuple[int, bool]:
    # kind: "sink" or "source"
    text = _run(["pactl", f"get-{kind}-volume", name])
    # "Volume: front-left: 32768 / 50% / -18.06 dB, ..."
    pct = 0
    for tok in text.split("/"):
        tok = tok.strip()
        if tok.endswith("%"):
            try:
                pct = int(tok[:-1])
                break
            except ValueError:
                pass
    mute_text = _run(["pactl", f"get-{kind}-mute", name]).strip()
    muted = "yes" in mute_text.lower()
    return pct, muted


def audio_state() -> dict | None:
    if not _has("pactl"):
        return None
    sinks = _list_short("sinks")
    sources = _list_short("sources")
    sink_descs = _description_map("sinks")
    src_descs = _description_map("sources")
    for s in sinks:
        s["name"] = sink_descs.get(s["id"], s["id"])
    for s in sources:
        # filter monitors out
        if s["id"].endswith(".monitor"):
            s["_monitor"] = True
        s["name"] = src_descs.get(s["id"], s["id"])
    sources = [s for s in sources if not s.get("_monitor")]

    out_id = _default_name("sink")
    in_id = _default_name("source")
    out_vol = out_mute = in_vol = in_mute = None
    if out_id:
        out_vol, out_mute = _volume_pct("sink", out_id)
    if in_id:
        in_vol, in_mute = _volume_pct("source", in_id)
    return {
        "outputs": sinks,
        "inputs": sources,
        "active_output_id": out_id,
        "active_input_id": in_id,
        "output_volume": out_vol or 0,
        "output_muted": bool(out_mute),
        "input_volume": in_vol or 0,
        "input_muted": bool(in_mute),
    }


# Pegelprobe: so kurz und grob wie moeglich, es geht nur um "still oder
# nicht". 8 kHz mono, 120 ms — 1920 Bytes. Ein stummer Strom (X.com mit
# Autoplay ohne Ton) liefert exakt 0, ein leiser Titel Hunderte.
_PROBE_RATE = 8000
_PROBE_S = 0.12
_PROBE_DEADLINE_S = 1.0
_SILENCE_PEAK = 64      # ~ -54 dBFS


def _sink_inputs(timeout: float = 0.5) -> list[tuple[int, int, bool]]:
    """(Index, PID, corked) je Ausgabestrom. Ein Sink-Input ist "corked",
    solange sein Programm pausiert."""
    out: list[tuple[int, int, bool]] = []
    index = pid = 0
    corked = True

    def flush():
        if index:
            out.append((index, pid, corked))

    for line in _run(["pactl", "list", "sink-inputs"], timeout).splitlines():
        s = line.strip()
        if s.startswith("Sink Input #"):
            flush()
            corked, pid = True, 0
            try:
                index = int(s.split("#", 1)[1])
            except ValueError:
                index = 0
        elif s.startswith("Corked:"):
            corked = s.split(":", 1)[1].strip().lower() != "no"
        elif s.startswith("application.process.id"):
            try:
                pid = int(s.split("=", 1)[1].strip().strip('"'))
            except ValueError:
                pid = 0
    flush()
    return out


def _stream_has_sound(index: int) -> bool | None:
    """Ob auf dem Strom gerade etwas zu hoeren ist. None = nicht messbar.

    ``parec --monitor-stream`` liest den Strom mit, ein paar Millisekunden
    lang. Blockiert bis zu einer Sekunde — nur aus einem Hintergrund-Thread
    rufen.
    """
    if not _has("parec"):
        return None
    wanted = int(_PROBE_RATE * 2 * _PROBE_S)
    try:
        proc = subprocess.Popen(
            ["parec", f"--monitor-stream={index}", "--format=s16le",
             f"--rate={_PROBE_RATE}", "--channels=1", "--raw",
             "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=_PACTL_ENV)
    except OSError:
        return None
    data = b""
    deadline = time.monotonic() + _PROBE_DEADLINE_S
    try:
        fd = proc.stdout.fileno()
        while len(data) < wanted:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _w, _x = select.select([fd], [], [], remaining)
            if not ready:
                break
            chunk = os.read(fd, wanted - len(data))
            if not chunk:
                break
            data += chunk
    finally:
        proc.kill()
        proc.wait()
    if len(data) < wanted // 2:
        return None
    count = len(data) // 2
    samples = struct.unpack(f"<{count}h", data[:count * 2])
    return max(abs(v) for v in samples) > _SILENCE_PEAK


def audible_pids() -> set[int]:
    """PIDs der Programme, aus denen gerade hoerbar Ton kommt.

    Das ist die Wahrheit ueber "spielt gerade", unabhaengig davon, was ein
    Player ueber MPRIS behauptet (Brave meldet dort "Paused", waehrend YouTube
    hoerbar laeuft — siehe sensors/mpris.py). "Corked" allein reicht nicht:
    ein Browser-Tab mit stummem Autoplay haelt seinen Strom offen und liefert
    Stille. Deshalb wird jeder offene Strom kurz mitgehoert.

    Die PID ist die des Prozesses, der den Strom haelt: bei Chromium ein
    Hilfsprozess, nicht der Browser selbst — der Aufrufer muss den Elternpfad
    hochgehen. Dauert bis zu einer Sekunde je Strom: nicht vom GTK-Thread aus.
    """
    pids: set[int] = set()
    for index, pid, corked in _sink_inputs():
        if corked or not pid:
            continue
        sound = _stream_has_sound(index)
        # Nicht messbar (kein parec): offen gilt als hoerbar.
        if sound is None or sound:
            pids.add(pid)
    return pids


# Welche Ereignisse von `pactl subscribe` eine neue Lesung lohnen. sink-input
# und source-output (jeder Stream, der auf- oder zugeht) absichtlich nicht —
# sie aendern nichts an dem, was das Panel zeigt, kaemen aber staendig.
_EVENT = re.compile(r" on (sink|source|server|card) #")


class AudioWatcher:
    """`pactl subscribe` im Hintergrund: sagt, ob sich seit dem letzten
    ``consume()`` etwas geaendert hat.

    Ohne das las der Aggregator alle 2 s sechs pactl-Aufrufe (36 ms) — fuer
    Werte, die sich minutenlang nicht ruehren. Mit Ereignissen wird nur
    gelesen, wenn Volume, Mute, Default-Geraet oder die Geraeteliste sich
    bewegt haben; dazu ein Sicherheitsintervall, falls ein Ereignis verloren
    geht. Stirbt der Prozess (kein Server, pactl fehlt), ist ``alive`` False
    und der Aggregator faellt auf das alte Polling zurueck.
    """

    def __init__(self) -> None:
        self._dirty = threading.Event()
        self._dirty.set()  # erste Lesung immer
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._alive = False
        self._stopped = False

    @property
    def alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        """Beobachter starten — oder neu starten, wenn der letzte gestorben ist.

        Beim Autostart ist der Sound-Server oft noch nicht da; `pactl
        subscribe` beendet sich dann sofort. Ein neuer Versuch spaeter (der
        Aggregator ruft das periodisch) holt den Ereignis-Modus zurueck, statt
        fuer den Rest der Sitzung zu pollen.
        """
        if self._stopped or not _has("pactl"):
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="xeneon-pactl",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def consume(self) -> bool:
        """True, wenn seit dem letzten Aufruf ein relevantes Ereignis kam."""
        was = self._dirty.is_set()
        self._dirty.clear()
        return was

    def _run(self) -> None:
        try:
            self._proc = subprocess.Popen(
                ["pactl", "subscribe"], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                text=True, env=_PACTL_ENV,
            )
        except OSError:
            return
        self._alive = True
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if _EVENT.search(line):
                    self._dirty.set()
        except (OSError, ValueError):
            pass
        finally:
            self._alive = False
            self._dirty.set()  # Rueckfall auf Polling beginnt mit frischer Lesung


def set_volume(kind: str, name: str, pct: int) -> None:
    pct = max(0, min(150, int(pct)))
    _run(["pactl", f"set-{kind}-volume", name, f"{pct}%"])


def set_mute(kind: str, name: str, muted: bool) -> None:
    _run(["pactl", f"set-{kind}-mute", name, "1" if muted else "0"])


def set_default(kind: str, name: str) -> None:
    _run(["pactl", f"set-default-{kind}", name])
