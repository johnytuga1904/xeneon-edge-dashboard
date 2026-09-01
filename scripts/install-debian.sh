#!/usr/bin/env bash
# Installer for Debian 13 (trixie) and derivatives.
#
#   ./scripts/install-debian.sh [options]
#
#   --no-autostart      skip the ~/.config/autostart entry
#   --monitor NAME      pin the dashboard to a DRM connector (e.g. DP-2)
#   --no-fullscreen     don't fullscreen on the target monitor
#   --yes               never ask anything (uses auto-detect for the monitor)
#   --no-packages       skip apt entirely (nur Settings/Autostart neu schreiben)
#   --check             only verify an existing install, install nothing
#
# Package names are the trixie ones. Python deps come from apt, not pip:
# Debian marks its Python as externally managed (PEP 668), so
# "pip install --user" aborts with an externally-managed-environment error.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AUTOSTART=1
FULLSCREEN=1
MONITOR=""
ASSUME_YES=0
CHECK_ONLY=0
DO_PACKAGES=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-autostart)  AUTOSTART=0 ;;
    --no-fullscreen) FULLSCREEN=0 ;;
    --monitor)       MONITOR="${2:?--monitor needs a connector name}"; shift ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --no-packages)   DO_PACKAGES=0 ;;
    --check)         CHECK_ONLY=1 ;;
    -h|--help)       sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1;31m▸ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- 1. platform

say "System prüfen"
if [[ ! -r /etc/os-release ]]; then
  bad "/etc/os-release fehlt — kein Debian?"; exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
echo "  ${PRETTY_NAME:-?}  (ID=${ID:-?} ${VERSION_CODENAME:-?})"
case "${ID:-}:${ID_LIKE:-}" in
  debian:*|*:*debian*) ;;
  *) warn "Kein Debian/Debian-Derivat — Paketnamen können abweichen." ;;
esac
if [[ "${VERSION_CODENAME:-}" != "trixie" ]]; then
  warn "Skript ist für trixie (Debian 13) geschrieben; auf ${VERSION_CODENAME:-?} können Namen abweichen."
fi
[[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] || warn "Keine Display-Session — GUI-Teile werden hier nicht laufen."

# NVIDIA nur anfassen, wenn wirklich eine NVIDIA-Karte steckt.
# Kein "| grep -q" hier: grep -q beendet sich beim ersten Treffer, das linke
# Kommando stirbt an SIGPIPE und die Pipeline gilt unter pipefail als Fehler.
HAS_NVIDIA=0
GPUS=""
if command -v lspci >/dev/null 2>&1; then
  GPUS="$(lspci -nn 2>/dev/null | grep -i 'vga\|3d controller' || true)"
fi
if [[ -n "$GPUS" ]]; then
  printf '%s\n' "$GPUS" | sed 's/^/  GPU: /'
  if grep -qi nvidia <<<"$GPUS"; then HAS_NVIDIA=1; fi
fi
# lspci fehlt in manchen Minimal-Installationen — Kernelmodul als Fallback.
if [[ -e /proc/driver/nvidia || -e /sys/module/nvidia ]]; then HAS_NVIDIA=1; fi
if (( HAS_NVIDIA )); then ok "NVIDIA erkannt — nvidia-smi wird mitinstalliert"; fi

# ---------------------------------------------------------------- 2. packages

PKGS=(
  python3-gi            # PyGObject
  python3-gi-cairo
  gir1.2-gtk-4.0        # GTK4 typelib
  gir1.2-adw-1          # libadwaita typelib
  gir1.2-webkit-6.0     # WebKitGTK 6.0 — TradingView chart
  python3-psutil        # top processes
  python3-requests      # weather + match fixtures
  lm-sensors            # hwmon fan/temp labels
  pulseaudio-utils      # pactl (volume, default device)
  wireplumber           # wpctl (PipeWire fallback path)
)
# nvidia-smi liegt in der non-free-Komponente
if (( HAS_NVIDIA )); then PKGS+=(nvidia-smi); fi

if (( ! CHECK_ONLY && DO_PACKAGES )); then
  say "Pakete installieren"
  if ! command -v apt-cache >/dev/null 2>&1; then
    bad "apt-cache nicht gefunden — dieses Skript braucht Debian/apt."
    bad "Nur Settings + Autostart schreiben: $0 --no-packages"
    exit 1
  fi
  MISSING=()
  for p in "${PKGS[@]}"; do
    # awk statt "grep -q": liest die Eingabe vollständig, kein SIGPIPE.
    CAND="$(apt-cache policy -- "$p" 2>/dev/null | awk '/Candidate:/ {print $2; exit}' || true)"
    if [[ -n "$CAND" && "$CAND" != "(none)" ]]; then
      MISSING+=("$p")
    else
      warn "$p ist in den aktiven Repos nicht verfügbar — übersprungen"
      if [[ "$p" == "nvidia-smi" ]]; then
        warn "  nvidia-smi liegt in 'non-free': deb ... trixie main contrib non-free non-free-firmware"
      fi
    fi
  done
  if (( ${#MISSING[@]} )); then
    echo "  apt-get install: ${MISSING[*]}"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends "${MISSING[@]}"
  fi
fi

# ---------------------------------------------------------------- 3. verify

say "Installation verifizieren"
cd "$ROOT"
VERIFY_RC=0
python3 scripts/verify-install.py || VERIFY_RC=$?
if (( VERIFY_RC )); then
  bad "Pflicht-Abhängigkeiten fehlen — Autostart/Settings werden nicht geschrieben."
  exit 1
fi

if (( CHECK_ONLY )); then say "Nur Check gewünscht — fertig."; exit 0; fi

# ---------------------------------------------------------------- 4. monitor

say "Monitor wählen"
MONITORS="$(python3 - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk
Gtk.init()
from xeneon_edge.ui.monitors import list_monitors_for_settings
d = Gdk.Display.get_default()
if d is not None:
    for conn, label in list_monitors_for_settings(d):
        print(f"{conn}\t{label}")
PY
)" || true

if [[ -n "$MONITORS" ]]; then
  printf '%s\n' "$MONITORS" | sed 's/^/  /' | expand -t 4
  if [[ -z "$MONITOR" ]] && (( ! ASSUME_YES )); then
    echo
    echo "  Leer lassen = Auto-Erkennung (sucht einen 2560x720-Monitor)."
    read -r -p "  Connector für das Dashboard [auto]: " MONITOR || MONITOR=""
  fi
else
  warn "Konnte die Monitore nicht abfragen — Auto-Erkennung wird verwendet."
fi

if [[ -n "$MONITOR" ]]; then
  KNOWN=0
  while IFS=$'\t' read -r conn _; do
    if [[ "$conn" == "$MONITOR" ]]; then KNOWN=1; fi
  done <<<"$MONITORS"
  if (( ! KNOWN )); then warn "Connector '$MONITOR' ist gerade nicht angeschlossen — wird trotzdem gespeichert."; fi
fi

say "settings.json schreiben"
MONITOR="$MONITOR" FULLSCREEN="$FULLSCREEN" AUTOSTART="$AUTOSTART" python3 - <<'PY'
import os
from xeneon_edge import config_store
s = config_store.load_settings()
s["target_monitor"] = os.environ.get("MONITOR", "")
s["fullscreen_on_target"] = os.environ.get("FULLSCREEN") == "1"
s["auto_start"] = os.environ.get("AUTOSTART") == "1"
config_store.save_settings(s)
from xeneon_edge.paths import USER_SETTINGS_FILE
print(f"  {USER_SETTINGS_FILE}")
print(f"    target_monitor      = {s['target_monitor'] or '(auto: 2560x720)'}")
print(f"    fullscreen_on_target= {s['fullscreen_on_target']}")
PY

# ---------------------------------------------------------------- 5. autostart

if (( AUTOSTART )); then
  say "Autostart einrichten"
  "$ROOT/scripts/install-autostart.sh"
  # The repo path contains a space — verify the Exec= line survived quoting.
  DESK="$HOME/.config/autostart/xeneon-edge.desktop"
  if grep -q '^Exec="' "$DESK" && [[ -x "$ROOT/run.sh" ]]; then
    ok "Exec= korrekt gequotet"
  else
    bad "Exec= in $DESK prüfen (Pfad enthält Leerzeichen!)"
  fi
fi

say "Fertig"
echo "  Starten:  \"$ROOT/run.sh\""
echo "  Monitor/Apps später ändern:  Zahnrad-Button oben rechts"
