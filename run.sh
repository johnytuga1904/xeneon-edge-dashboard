#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Omarchy und andere HiDPI-Hyprland-Setups exportieren GDK_SCALE=2 fuer die
# ganze Session (~/.config/hypr/monitors.conf). Die Spaltenbreiten des
# Dashboards sind harte Pixel, zugeschnitten auf die 2560x720 des Xeneon Edge —
# bei Buffer-Scale 2 ist nur noch ein Viertel des Layouts im Bild. Fuer diesen
# Prozess also 1x, ueberschreibbar mit XENEON_GDK_SCALE.
export GDK_SCALE="${XENEON_GDK_SCALE:-1}"

# WebKits DMABUF-Renderer bleibt an. Er war hier lange aus, weil WebKitGTK
# auf manchen Multi-GPU-Systemen (AMD-Ausgabe + NVIDIA daneben, damals unter
# Fedora) seinen Buffer nicht durchreichte und die Chart-Spalte schwarz blieb.
# Der Shared-Memory-Fallback hat aber einen eigenen Fehler: alle paar Minuten
# uebergibt er einen halbfertigen Frame — die Chart-Spalte ist fuer ein bis
# zwei Frames leer, was auf dem Streifen wie ein Schwarzblitz aussieht
# (KMS-Mitschnitt 12.09.2026: zweimal in zwoelf Minuten, mit DMABUF in 35
# Minuten nie). Wer die schwarze Spalte bekommt, schaltet mit
# XENEON_WEBKIT_DMABUF=0 auf den Fallback zurueck.
if [[ "${XENEON_WEBKIT_DMABUF:-1}" == "0" ]]; then
  export WEBKIT_DISABLE_DMABUF_RENDERER=1
fi

# Beim Autostart geht stdout in eine Pipe, und Python puffert dann blockweise:
# die Log-Zeilen des Dashboards erreichen das Journal erst beim Beenden, wenn
# ueberhaupt. Fuer ein Programm, das im Hintergrund startet, ist das genau
# verkehrt herum.
export PYTHONUNBUFFERED=1

exec python3 -m xeneon_edge "$@"
