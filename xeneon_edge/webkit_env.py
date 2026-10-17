"""Umgebung fuer WebKit, bevor GTK den Bildschirm oeffnet.

Auf Rechnern mit zwei Grafikkarten (AMD fuer die Anzeige, NVIDIA nur fuer
Rechenlast) laedt jedes EGL-Programm ueber GLVND zuerst den NVIDIA-Treiber:
``/usr/share/glvnd/egl_vendor.d/10_nvidia.json`` steht vor ``50_mesa.json``,
und WebKit nimmt bei der Geraetewahl den ersten Render-Knoten, meist
``renderD128`` = NVIDIA. Der Web-Prozess des Charts rendert dann ueber einen
Treiber, der mit der Anzeige nichts zu tun hat — und ``libnvidia-eglcore``
ist hier mit identischer Adresse viermal abgestuerzt (SIGSEGV, Coredumps vom
16./17.10.2026, Treiber 610.57).

Eine Variable, mit der WebKitGTK 2.52 den Render-Knoten vorgibt, gibt es
nicht (``WEBKIT_DRM_RENDER_NODE`` kennt dieser Build nicht). Was geht, ist
GLVND selbst: ``__EGL_VENDOR_LIBRARY_FILENAMES`` auf die Mesa-Datei
beschraenken. Dann sieht WebKit ueber ``EGL_EXT_device_drm_render_node`` nur
noch die Mesa-Geraete und landet auf der AMD. Nachgemessen: null
NVIDIA-Bibliotheken im Web-Prozess, Chart laeuft.

Das greift nur, wenn es beide Welten gibt: ein NVIDIA-Knoten *und* ein
Mesa-Knoten. Reine NVIDIA- oder reine AMD/Intel-Rechner bleiben unberuehrt.
``XENEON_EGL_VENDOR=off`` schaltet es ab, ``=mesa`` erzwingt es; ist
``__EGL_VENDOR_LIBRARY_FILENAMES`` schon gesetzt, bleibt das so.

Muss vor dem ersten GTK-Aufruf laufen: GTK4 oeffnet EGL schon fuer den
Bildschirm, und GLVND liest die Variable beim ersten eglGetDisplay.
"""
from __future__ import annotations
import os
from pathlib import Path

MESA_VENDOR_FILE = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
DRM_DIR = Path("/sys/class/drm")
# Kernel-Treiber, die ueber Mesa rendern. Alles andere (nvidia) nicht.
MESA_DRIVERS = {"amdgpu", "radeon", "i915", "xe", "nouveau", "virtio_gpu", "vc4", "v3d",
                "panfrost", "msm", "lima", "etnaviv"}


def render_nodes() -> list[tuple[str, str]]:
    """``[(/dev/dri/renderD128, nvidia), ...]`` — Knoten mit Kernel-Treiber."""
    out = []
    try:
        entries = sorted(DRM_DIR.iterdir())
    except OSError:
        return out
    for e in entries:
        if not e.name.startswith("renderD"):
            continue
        try:
            driver = os.path.basename(os.path.realpath(e / "device" / "driver"))
        except OSError:
            driver = "?"
        out.append((f"/dev/dri/{e.name}", driver))
    return out


def choose() -> tuple[str | None, str]:
    """(Vendor-Datei oder None, Begruendung) — ohne Seiteneffekt, testbar."""
    mode = os.environ.get("XENEON_EGL_VENDOR", "auto").lower()
    if mode == "off":
        return None, "XENEON_EGL_VENDOR=off"
    if os.environ.get("__EGL_VENDOR_LIBRARY_FILENAMES"):
        return None, "__EGL_VENDOR_LIBRARY_FILENAMES is already set"
    if not MESA_VENDOR_FILE.exists():
        return None, f"{MESA_VENDOR_FILE} is missing"
    nodes = render_nodes()
    nvidia = [n for n, d in nodes if d == "nvidia"]
    mesa = [n for n, d in nodes if d in MESA_DRIVERS]
    if mode == "mesa":
        return str(MESA_VENDOR_FILE), "XENEON_EGL_VENDOR=mesa"
    if nvidia and mesa:
        return str(MESA_VENDOR_FILE), (f"NVIDIA ({', '.join(nvidia)}) next to Mesa "
                                       f"({', '.join(mesa)}) — WebKit on Mesa")
    return None, "no mixed NVIDIA/Mesa setup"


def apply(verbose: bool = True) -> bool:
    """Setzt die GLVND-Variable, wenn ``choose()`` eine Datei nennt."""
    vendor, why = choose()
    if vendor is None:
        return False
    os.environ["__EGL_VENDOR_LIBRARY_FILENAMES"] = vendor
    if verbose:
        print(f"[xeneon-edge] EGL via Mesa only: {why}", flush=True)
    return True
