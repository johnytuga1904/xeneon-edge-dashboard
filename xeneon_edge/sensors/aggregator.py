"""1 Hz background polling — pushes Snapshot to a callback on the GTK main loop.

Gelesen wird nur, was ein sichtbares Modul braucht (``needs``, siehe
modules/): wer die Luefter ausblendet, spart das hwmon-Polling; ohne
Prozess-Modul entfaellt der psutil-Durchlauf. Netz, Wetter und Spiel haengen
an der Topbar und werden immer gelesen.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import threading
import time
from typing import Callable

from . import cpu as cpu_mod
from . import ram as ram_mod
from . import net as net_mod
from . import fans as fans_mod
from . import gpu_amd as gpu_amd_mod
from . import gpu_nvidia as gpu_nvidia_mod
from . import processes as proc_mod
from . import audio as audio_mod
from . import weather as weather_mod
from . import match as match_mod


@dataclass
class Snapshot:
    cpu: dict = field(default_factory=dict)
    gpus: list[dict] = field(default_factory=list)
    ram: dict = field(default_factory=dict)
    fans: list[dict] = field(default_factory=list)
    net: dict = field(default_factory=dict)
    processes: list[dict] = field(default_factory=list)
    audio: dict | None = None
    weather: dict | None = None
    next_match: dict | None = None
    cpu_name: str = "CPU"
    # Wann dieser Snapshot entstand (time.time()). Die Statuspille erkennt
    # daran einen haengenden Sensor-Thread — ohne das sieht ein eingefrorenes
    # Dashboard aus wie ein ruhiges System.
    taken_at: float = 0.0
    # Welcher Treiber welchen Wert geliefert hat, z.B. {"gpu": "amdgpu"}.
    sources: dict = field(default_factory=dict)


# Alle abschaltbaren Subsysteme; Default, solange kein Layout etwas anderes sagt.
ALL_NEEDS = frozenset({"cpu", "gpu", "ram", "fans", "processes", "audio"})

# Audio ohne Ereignisse: alte Rate. Mit Ereignissen: nur zur Sicherheit.
_AUDIO_POLL_S = 2.0
_AUDIO_SAFETY_S = 30.0


class Aggregator:
    def __init__(self, on_snapshot: Callable[[Snapshot], None] | None = None,
                 interval: float = 1.0,
                 needs: frozenset[str] | None = None) -> None:
        self._on_snapshot = on_snapshot
        self._interval = interval
        self.needs: frozenset[str] = ALL_NEEDS if needs is None else frozenset(needs)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cpu_load = cpu_mod.CpuLoadTracker()
        self._net = net_mod.NetTracker()
        self._cpu_name = cpu_mod.cpu_name()
        self.snapshot = Snapshot(cpu_name=self._cpu_name)
        self._weather_last_fetch = 0.0
        self._weather_cache: dict | None = None
        self._audio_skip_until = 0.0  # Polling-Rueckfall, wenn pactl subscribe nicht laeuft
        self._audio_last_read = 0.0
        self._audio_watch = audio_mod.AudioWatcher()
        self._match_last_fetch = 0.0
        self._match_cache: dict | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="xeneon-sensors",
                                        daemon=True)
        self._thread.start()
        self._audio_watch.start()

    def stop(self) -> None:
        self._stop.set()
        self._audio_watch.stop()

    def set_needs(self, needs: frozenset[str]) -> None:
        """Vom Layout aufgerufen; wirkt ab dem naechsten Tick.

        Nur Lesezugriff aus dem Sensor-Thread, Zuweisung ist atomar — kein
        Lock noetig.
        """
        self.needs = frozenset(needs)

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            self._tick()
            elapsed = time.monotonic() - t0
            sleep_for = max(0.05, self._interval - elapsed)
            self._stop.wait(sleep_for)

    def _tick(self) -> None:
        snap = Snapshot(cpu_name=self._cpu_name)
        needs = self.needs

        if "cpu" in needs:
            snap.cpu = {
                "load_pct": self._cpu_load.sample(),
                "clock_mhz": cpu_mod.cpu_clock_mhz(),
                "temp_c": cpu_mod.cpu_temp_c(),
                "power_w": None,  # RAPL is slow (50ms blocking) — fetch every 5 ticks
            }
        if "ram" in needs:
            snap.ram = ram_mod.ram_metrics() or {}
        d_mbps, u_mbps = self._net.sample()
        snap.net = {"down_mbps": d_mbps, "up_mbps": u_mbps}
        if "fans" in needs:
            snap.fans = fans_mod.fan_metrics()

        if "gpu" in needs:
            amd = gpu_amd_mod.gpu_amd_metrics()
            nvidia = gpu_nvidia_mod.gpu_nvidia_metrics()
            snap.gpus = amd + nvidia
            # Welche Treiber wirklich etwas geliefert haben — die Statuspille
            # zeigt es an, damit sichtbar ist, woher die Werte kommen.
            # Kurze Namen: die Statuspille hat eine feste Breite, und mit zwei
            # GPUs wird "amdgpu+nvidia" dort abgeschnitten.
            found = [name for name, found_gpus in (("amd", amd), ("nv", nvidia))
                     if found_gpus]
            if found:
                snap.sources["gpu"] = "+".join(found)
            nv_src = gpu_nvidia_mod.source_name()
            if nv_src:
                snap.sources["nvidia"] = nv_src

        if "processes" in needs:
            snap.processes = proc_mod.top_processes(14)

        now = time.monotonic()
        if "audio" in needs:
            if self._audio_watch.alive:
                refresh = (self._audio_watch.consume()
                           or now - self._audio_last_read >= _AUDIO_SAFETY_S)
            else:
                refresh = now >= self._audio_skip_until
            if refresh:
                try:
                    snap.audio = audio_mod.audio_state()
                except Exception:
                    snap.audio = None
                self._audio_last_read = now
                self._audio_skip_until = now + _AUDIO_POLL_S
            else:
                snap.audio = self.snapshot.audio

        if now - self._weather_last_fetch > 600:  # 10 min
            try:
                self._weather_cache = weather_mod.fetch_weather()
            except Exception:
                pass
            self._weather_last_fetch = now
        snap.weather = self._weather_cache

        if now - self._match_last_fetch > 3600:  # 1 hour
            try:
                self._match_cache = match_mod.fetch_next_match()
            except Exception:
                pass
            self._match_last_fetch = now
        snap.next_match = self._match_cache

        snap.taken_at = time.time()
        self.snapshot = snap
        if self._on_snapshot is not None:
            try:
                self._on_snapshot(snap)
            except Exception as e:  # pragma: no cover
                print(f"[xeneon-edge] snapshot callback error: {e}")
