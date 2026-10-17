#!/usr/bin/env python3
"""Prueft die Laufzeit-Abhaengigkeiten des Dashboards — distro-unabhaengig.

Wird von install-arch.sh und install-debian.sh benutzt (und laesst sich einzeln
aufrufen: ``python3 scripts/verify-install.py``). Exit 1, sobald eine
Pflicht-Abhaengigkeit fehlt; Optionales gibt nur eine Warnung.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

rc = 0


def ok(m: str) -> None:
    print(f"  \033[32m✓\033[0m {m}")


def bad(m: str) -> None:
    print(f"  \033[31m✗\033[0m {m}")


def warn(m: str) -> None:
    print(f"  \033[33m!\033[0m {m}")


import gi  # noqa: E402  (nach den Helpern, damit ein Fehler lesbar bleibt)

for ns, ver, hard in (("Gtk", "4.0", True), ("Gdk", "4.0", True),
                      ("Adw", "1", True), ("WebKit", "6.0", False)):
    try:
        gi.require_version(ns, ver)
        __import__("gi.repository", fromlist=[ns])
        ok(f"{ns} {ver}")
    except Exception as e:
        (bad if hard else warn)(f"{ns} {ver}: {e}")
        if hard:
            rc = 1
        else:
            warn("  → Chart-Panel zeigt den Platzhalter statt TradingView")

for mod, hard in (("psutil", True), ("requests", False)):
    try:
        __import__(mod)
        ok(mod)
    except ImportError as e:
        (bad if hard else warn)(f"{mod}: {e}")
        if hard:
            rc = 1

# WebKitGTK baut fuer jedes <audio>/AudioContext eine GStreamer-Pipeline und
# verlangt darin autoaudiosink namentlich. Fehlt das Element, bekommt WebKit
# NULL zurueck, haengt trotzdem einen Signal-Handler daran und bricht ab —
# der WebKitWebProcess stirbt mit SIGABRT, sobald TradingView Ton anfasst.
# autoaudiosink kommt aus gst-plugins-good, das bei webkitgtk nur eine
# *optionale* Abhaengigkeit ist und deshalb gerne fehlt.
if shutil.which("gst-inspect-1.0"):
    found = subprocess.run(["gst-inspect-1.0", "autoaudiosink"],
                           capture_output=True).returncode == 0
    if found:
        ok("autoaudiosink — GStreamer-Audiosenke fuer WebKit")
    else:
        warn("autoaudiosink fehlt — WebKit stirbt beim TradingView-Login")
        warn("  → Arch:   sudo pacman -S gst-plugins-good")
        warn("  → Debian: sudo apt install gstreamer1.0-plugins-good")
        warn("  → Fedora: sudo dnf install gstreamer1-plugins-good")
else:
    warn("gst-inspect-1.0 nicht da — autoaudiosink nicht pruefbar")

# Der Musikordner spielt ueber eine eigene GStreamer-Pipeline (ui/localplayer.py)
# und braucht dafuer die Python-Bindings, nicht nur die Plugins.
try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst  # noqa: E402,F401
    ok("Gst-1.0 — GStreamer-Bindings fuer den Musikordner")
except (ValueError, ImportError):
    warn("Gst-1.0-Typelib fehlt — der Musikordner im Wiedergabe-Modul bleibt stumm")
    warn("  → Arch:   in 'gstreamer' enthalten")
    warn("  → Debian: sudo apt install gir1.2-gstreamer-1.0")
    warn("  → Fedora: sudo dnf install python3-gstreamer1")

# NVML-Bindings sind optional: ohne sie laeuft nvidia-smi als Prozessstart pro
# Tick (28 ms statt 0,1 ms). Nur erwaehnen, wenn ueberhaupt eine NVIDIA da ist.
if shutil.which("nvidia-smi"):
    try:
        __import__("pynvml")
        ok("pynvml — NVIDIA-Werte ueber NVML")
    except ImportError:
        warn("pynvml fehlt — NVIDIA-Werte ueber nvidia-smi (28 ms pro Tick)")
        warn("  → Arch:   sudo pacman -S python-nvidia-ml-py")
        warn("  → Debian: sudo apt install python3-pynvml")

for tool, what in (("pactl", "Audio-Lautstaerke/Default-Device"),
                   ("wpctl", "PipeWire-Fallback"),
                   ("sensors", "hwmon-Labels"),
                   ("systemd-run", "isolierte Deck-Starts (isolate_launches)"),
                   ("nvidia-smi", "NVIDIA-GPU-Panel")):
    (ok if shutil.which(tool) else warn)(f"{tool} — {what}")

# Sensor-Pfade, die der Aggregator liest
for p, what in (("/proc/stat", "CPU-Last"), ("/proc/meminfo", "RAM"),
                ("/proc/net/dev", "Netzwerk"), ("/sys/class/hwmon", "Temp/Luefter"),
                ("/sys/class/drm", "AMD-GPU")):
    (ok if Path(p).exists() else warn)(f"{p} — {what}")

# Session-Umgebung. GDK_SCALE ist der Klassiker auf Hyprland/Omarchy: dort steht
# session-weit GDK_SCALE=2 fuer HiDPI-Notebooks, und die Spaltenbreiten des
# Dashboards sind harte Pixel fuer die 2560x720 des Xeneon Edge.
scale = os.environ.get("GDK_SCALE", "")
if scale and scale not in ("1", "1.0"):
    warn(f"GDK_SCALE={scale} in dieser Session — run.sh erzwingt fuer das "
         "Dashboard 1 (ueberschreibbar mit XENEON_GDK_SCALE)")
else:
    ok(f"GDK_SCALE={scale or '(nicht gesetzt)'}")

desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
session = os.environ.get("XDG_SESSION_TYPE", "")
if desktop or session:
    ok(f"Session: {desktop or '?'} / {session or '?'}")
else:
    warn("Keine Display-Session — die GUI-Teile laufen hier nicht")

# Datei-Picker im Settings-Dialog (Gtk.FileDialog) laeuft unter Wayland ueber
# den Portal-Dienst.
if session == "wayland" and not any(
    Path(d, "xdg-desktop-portal").exists() or Path(d, "xdg-desktop-portal-gtk").exists()
    for d in ("/usr/libexec", "/usr/lib", "/usr/lib/xdg-desktop-portal")
):
    warn("xdg-desktop-portal nicht gefunden — 'Browse' im Settings-Dialog bleibt leer")

sys.exit(rc)
