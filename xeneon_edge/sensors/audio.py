"""PipeWire/PulseAudio control via pactl + wpctl."""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import threading


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
