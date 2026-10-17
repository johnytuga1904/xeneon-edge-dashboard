#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Omarchy und andere HiDPI-Hyprland-Setups exportieren GDK_SCALE=2 fuer die
# ganze Session (~/.config/hypr/monitors.conf). Die Spaltenbreiten des
# Dashboards sind harte Pixel, zugeschnitten auf die 2560x720 des Xeneon Edge —
# bei Buffer-Scale 2 ist nur noch ein Viertel des Layouts im Bild. Fuer diesen
# Prozess also 1x, ueberschreibbar mit XENEON_GDK_SCALE.
export GDK_SCALE="${XENEON_GDK_SCALE:-1}"

# WebKitGTK reicht seinen DMABUF-Buffer auf manchen Multi-GPU-Systemen
# (AMD-Ausgabe + NVIDIA daneben) nicht durch: der WebProcess laeuft, die Seite
# laedt, sichtbar bleibt eine schwarze Chart-Spalte. Nachgemessen am
# 17.10.2026 (Omarchy, WebKitGTK 2.52.6): mit DMABUF-Renderer schwarz, mit
# und ohne Mesa-Zwang (webkit_env.py); mit dem Fallback-Renderer sichtbar.
# Deshalb ist der Fallback wieder Standard. Im September war DMABUF kurz der
# Standard, weil der Fallback alle paar Minuten ein schwarzes Einzelbild
# zeigte — ob das mit WebKit auf Mesa statt NVIDIA-EGL noch auftritt, ist
# offen. XENEON_WEBKIT_DMABUF=1 schaltet den DMABUF-Renderer wieder ein.
if [[ "${XENEON_WEBKIT_DMABUF:-0}" != "1" ]]; then
  export WEBKIT_DISABLE_DMABUF_RENDERER=1
fi

# Beim Autostart geht stdout in eine Pipe, und Python puffert dann blockweise:
# die Log-Zeilen des Dashboards erreichen das Journal erst beim Beenden, wenn
# ueberhaupt. Fuer ein Programm, das im Hintergrund startet, ist das genau
# verkehrt herum.
export PYTHONUNBUFFERED=1

exec python3 -m xeneon_edge "$@"
