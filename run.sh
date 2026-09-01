#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Omarchy und andere HiDPI-Hyprland-Setups exportieren GDK_SCALE=2 fuer die
# ganze Session (~/.config/hypr/monitors.conf). Die Spaltenbreiten des
# Dashboards sind harte Pixel, zugeschnitten auf die 2560x720 des Xeneon Edge —
# bei Buffer-Scale 2 ist nur noch ein Viertel des Layouts im Bild. Fuer diesen
# Prozess also 1x, ueberschreibbar mit XENEON_GDK_SCALE.
export GDK_SCALE="${XENEON_GDK_SCALE:-1}"

exec python3 -m xeneon_edge "$@"
