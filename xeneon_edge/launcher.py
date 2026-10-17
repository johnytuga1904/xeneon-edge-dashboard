"""Starten von Deck-Eintraegen — isoliert in eigenen systemd-Units.

Warum nicht einfach ``subprocess.Popen``: ``start_new_session=True`` macht nur
eine neue Session/Prozessgruppe, **keine** neue cgroup. Ein so gestarteter
Prozess bleibt Kind des Dashboards und laeuft in dessen Unit
(``app-xeneon-edge@autostart.service``). Bei einem lokalen LLM-Server mit
``--threads 16`` und zweistelligen GB heisst das:

* CPU-Weight und Memory-Reclaim teilen sich UI und Modell in einer cgroup —
  das Dashboard ruckelt beim Laden und waehrend der Inferenz;
* ``systemctl --user restart`` des Dashboards erschiesst den Modellserver mit
  (KillMode=control-group ist Default);
* Stop-Skripte, die die Unit aus ``/proc/PID/cgroup`` ableiten, finden die
  Dashboard-Unit und stoppen das Dashboard statt des Servers;
* das ``Popen``-Objekt wird weggeworfen, nie ``wait()`` — jeder beendete
  Server bleibt als Zombie im Dashboard haengen.

Default ist deshalb ``systemd-run --user``: eigene transiente Unit, eigene
cgroup, eigenes OOM-Accounting, Logs im Journal, ueberlebt einen
Dashboard-Neustart und ist per ``systemctl --user stop <unit>`` sauber zu
beenden.

Abschalten global ueber Settings (``isolate_launches``) oder pro Eintrag mit
``"launch": "direct"`` in apps.json — noetig nur, wenn ein Kommando zwingend
Kind des Dashboards bleiben muss.
"""
from __future__ import annotations
import re
import shlex
import shutil
import subprocess

# Eigener Prefix, damit ein Deck-Eintrag nie den Namen einer echten Unit
# trifft — bei "id": "edge" waere das sonst xeneon-edge.service, und
# systemd-run scheitert an "already loaded or has a fragment file".
UNIT_PREFIX = "xeneon-deck-"

# systemd-Unitnamen duerfen nur diese Zeichen enthalten (alles andere muesste
# escaped werden — hier stattdessen ersetzt, der Name ist rein kosmetisch).
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")

# Kurzlebige systemd-run-Aufrufe, die noch nicht abgeraeumt sind. Ohne
# ``poll()`` sammelt das Dashboard fuer jeden Klick einen Zombie an.
_children: list[subprocess.Popen] = []


def _reap() -> None:
    for proc in list(_children):
        if proc.poll() is not None:
            _children.remove(proc)


def unit_name(entry: dict, slot: int | None = None) -> str:
    """Stabiler Unitname pro Deck-Eintrag, z.B. ``xeneon-deck-02-macro2``.

    Stabil, damit ein laufender Eintrag per ``systemctl --user stop`` gezielt
    beendet werden kann. Nebeneffekt: ein zweiter Klick auf einen bereits
    laufenden Eintrag scheitert an "unit already exists" statt eine zweite
    Instanz zu starten — genau das gewollte Verhalten bei Modellservern.

    Die Slotnummer gehoert mit in den Namen, weil ``id`` nicht eindeutig ist:
    beim Umsortieren im Settings-Dialog wandern die Eintraege, ihre ``id``
    bleibt stehen — in echten Configs stehen dadurch schon mal zwei Slots auf
    ``macro5``. Ohne Slotnummer koennte der zweite davon nicht starten,
    solange der erste laeuft.
    """
    raw = str(entry.get("id") or entry.get("label") or "entry")
    slug = _UNSAFE.sub("-", raw).strip("-.").lower() or "entry"
    prefix = UNIT_PREFIX if slot is None else f"{UNIT_PREFIX}{slot + 1:02d}-"
    return f"{prefix}{slug[:48]}"


def _argv(entry: dict) -> list[str] | None:
    cmd = entry.get("command")
    if not cmd:
        return None
    try:
        return [cmd] + shlex.split(entry.get("args") or "")
    except ValueError as e:  # unbalancierte Quotes in args
        print(f"[xeneon-edge] bad args for {entry.get('id')}: {e}")
        return None


def _use_systemd(entry: dict, isolate: bool) -> bool:
    if str(entry.get("launch") or "").lower() == "direct":
        return False
    return isolate and shutil.which("systemd-run") is not None


# Welche der beiden hyprctl-Schreibweisen dieser Rechner versteht. None =
# noch nicht ausprobiert. Siehe focus_monitor().
_FOCUS_FORM: str | None = None


def _focus_argv(form: str, connector: str) -> list[str]:
    if form == "lua":
        return ["hyprctl", "dispatch", f'hl.dsp.focus({{ monitor = "{connector}" }})']
    return ["hyprctl", "dispatch", "focusmonitor", connector]


def focus_monitor(connector: str) -> None:
    """Den Compositor auf ``connector`` fokussieren, bevor etwas startet.

    Neue Fenster gehen auf dem fokussierten Ausgang auf. Ohne diesen Schritt
    landet ein Deck-Start dort, wo zuletzt der Fokus lag — mitunter auf dem
    Streifen selbst, wo das Dashboard im Vollbild davorliegt und keine
    Tastatur haengt. Das Fenster ist dann gestartet, aber unerreichbar.

    Zwei Schreibweisen, weil es zwei hyprctl gibt: die klassische
    (``dispatch focusmonitor DP-4``) und die neuere mit Lua-Konfiguration, wie
    Omarchy sie mitbringt — dort zerlegt ein Lua-Parser die Argumente und
    ``DP-4`` wird als Rechnung "DP minus 4" gelesen ("')' expected near 'DP'").
    Welche Form geht, entscheidet der erste Aufruf; danach steht sie fest.

    Nur Hyprland, und nur best effort: fehlt ``hyprctl`` oder laeuft ein
    anderer Compositor, bleibt es beim Standardverhalten. Ein Fehlschlag darf
    den Start nie verhindern — lieber ein Fenster auf dem falschen Monitor als
    gar keines.
    """
    global _FOCUS_FORM
    if not connector or not shutil.which("hyprctl"):
        return

    forms = [_FOCUS_FORM] if _FOCUS_FORM else ["classic", "lua"]
    for form in forms:
        try:
            done = subprocess.run(_focus_argv(form, connector),
                                  capture_output=True, text=True,
                                  timeout=1, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"[xeneon-edge] focusmonitor {connector} failed: {e}")
            return
        # hyprctl meldet einen Fehler im Text, nicht immer im Exitcode.
        output = (done.stdout or "") + (done.stderr or "")
        if done.returncode == 0 and "error" not in output.lower():
            _FOCUS_FORM = form
            return
    print(f"[xeneon-edge] could not focus monitor {connector} "
          f"— windows open wherever the compositor puts them")


def launch(entry: dict, *, isolate: bool = True, slot: int | None = None,
           monitor: str = "") -> None:
    _reap()
    argv = _argv(entry)
    if argv is None:
        return

    focus_monitor(monitor)

    label = entry.get("label") or entry.get("id") or argv[0]

    if _use_systemd(entry, isolate):
        unit = unit_name(entry, slot)
        argv = [
            "systemd-run", "--user", "--quiet", "--collect",
            f"--unit={unit}",
            f"--description=Xeneon Edge: {label}",
            "--same-dir",
            "--",
            *argv,
        ]
        print(f"[xeneon-edge] launch {label} -> {unit}.service")
        # stderr bleibt geerbt: systemd-run ist kurzlebig, und --quiet gibt nur
        # noch echte Fehler aus ("unit already exists", "command not found").
        # Die landen so im Journal der Dashboard-Unit. Die Ausgabe des
        # gestarteten Programms geht in dessen eigene Unit, nicht hierher.
        stderr = None
    else:
        print(f"[xeneon-edge] launch {label} (direct)")
        stderr = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(
            argv, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr,
        )
    except FileNotFoundError:
        print(f"[xeneon-edge] command not found: {argv[0]}")
        return
    except OSError as e:
        print(f"[xeneon-edge] failed to launch {label}: {e}")
        return

    _children.append(proc)
