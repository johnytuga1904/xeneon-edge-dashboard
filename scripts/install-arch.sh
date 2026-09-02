#!/usr/bin/env bash
# Installer fuer Arch Linux und Arch-Derivate — getestet gegen Omarchy
# (Arch + Hyprland + uwsm).
#
#   ./scripts/install-arch.sh [options]
#
#   --no-autostart      keinen ~/.config/autostart-Eintrag schreiben
#   --monitor NAME      Dashboard auf einen DRM-Connector pinnen (z.B. DP-2)
#   --no-fullscreen     nicht auf dem Zielmonitor in den Vollbildmodus gehen
#   --deck omarchy      Deck mit Omarchy-Kommandos vorbelegen (nur wenn es
#                       noch keine ~/.config/xeneon-edge/apps.json gibt)
#   --no-hypr           kein Hyprland-Snippet (Fensterregeln) schreiben
#   --yes               nichts nachfragen (Monitor per Auto-Erkennung)
#   --no-packages       pacman ueberspringen (nur Settings/Autostart schreiben)
#   --check             nur pruefen, nichts installieren
#
# Paketnamen sind die aus [core]/[extra]; alles liegt in den offiziellen Repos,
# ein AUR-Helper wird nicht gebraucht. Python-Abhaengigkeiten kommen aus pacman,
# nicht aus requirements.txt: Arch markiert sein Python als externally managed
# (PEP 668), "pip install --user" bricht mit externally-managed-environment ab.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AUTOSTART=1
FULLSCREEN=1
MONITOR=""
ASSUME_YES=0
CHECK_ONLY=0
DO_PACKAGES=1
DO_HYPR=1
DECK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-autostart)  AUTOSTART=0 ;;
    --no-fullscreen) FULLSCREEN=0 ;;
    --monitor)       MONITOR="${2:?--monitor needs a connector name}"; shift ;;
    --deck)          DECK="${2:?--deck needs omarchy|keep}"; shift ;;
    --no-hypr)       DO_HYPR=0 ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --no-packages)   DO_PACKAGES=0 ;;
    --check)         CHECK_ONLY=1 ;;
    -h|--help)       awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1;31m▸ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- 1. platform

say "System pruefen"
if [[ ! -r /etc/os-release ]]; then
  bad "/etc/os-release fehlt — kein Arch?"; exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
echo "  ${PRETTY_NAME:-?}  (ID=${ID:-?})"
case "${ID:-}:${ID_LIKE:-}" in
  arch:*|*:*arch*) ;;
  *) warn "Kein Arch/Arch-Derivat — Paketnamen koennen abweichen." ;;
esac

IS_OMARCHY=0
OMARCHY_DIR="${OMARCHY_PATH:-$HOME/.local/share/omarchy}"
if [[ -d "$OMARCHY_DIR" ]] || command -v omarchy-menu >/dev/null 2>&1; then
  IS_OMARCHY=1
  OMV="$(command -v omarchy-version >/dev/null 2>&1 && omarchy-version 2>/dev/null || true)"
  ok "Omarchy erkannt${OMV:+ ($OMV)}"
fi
if command -v hyprctl >/dev/null 2>&1; then
  ok "Hyprland: $(hyprctl version -j 2>/dev/null | sed -n 's/.*"tag": *"\([^"]*\)".*/\1/p' | head -1 || echo "?")"
fi
[[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] || warn "Keine Display-Session — GUI-Teile laufen hier nicht."

# NVIDIA nur melden, nicht installieren: nvidia-smi kommt aus nvidia-utils, und
# das haengt am Treiber-Paket (nvidia / nvidia-open / -dkms). Blind
# nachinstallieren wuerde sich mit der vorhandenen Variante beissen.
HAS_NVIDIA=0
if command -v lspci >/dev/null 2>&1; then
  GPUS="$(lspci -nn 2>/dev/null | grep -i 'vga\|3d controller' || true)"
  [[ -n "$GPUS" ]] && printf '%s\n' "$GPUS" | sed 's/^/  GPU: /'
  grep -qi nvidia <<<"${GPUS:-}" && HAS_NVIDIA=1
fi
[[ -e /proc/driver/nvidia || -e /sys/module/nvidia ]] && HAS_NVIDIA=1
if (( HAS_NVIDIA )) && ! command -v nvidia-smi >/dev/null 2>&1; then
  warn "NVIDIA-Karte, aber kein nvidia-smi — kommt aus 'nvidia-utils'"
  warn "  (auf Omarchy: Treiber ueber 'omarchy-install-nvidia' einrichten)"
fi

# ---------------------------------------------------------------- 2. packages

PKGS=(
  python-gobject        # PyGObject
  python-cairo
  gtk4                  # GTK4 inkl. Typelib
  libadwaita            # Adw
  webkitgtk-6.0         # WebKitGTK 6.0 — TradingView-Chart
  python-psutil         # Top-Prozesse
  python-requests       # Wetter + Match-Fixtures
  lm_sensors            # hwmon-Labels
  libpulse              # pactl (Lautstaerke, Default-Device)
  wireplumber           # wpctl (PipeWire-Fallback)
  pciutils              # lspci (GPU-Erkennung)
  adwaita-icon-theme    # Icon-Fallbacks im Deck
  xdg-desktop-portal-gtk # Datei-Picker im Settings-Dialog unter Wayland
)

if (( ! CHECK_ONLY && DO_PACKAGES )); then
  say "Pakete installieren"
  if ! command -v pacman >/dev/null 2>&1; then
    bad "pacman nicht gefunden — dieses Skript braucht Arch."
    bad "Nur Settings + Autostart schreiben: $0 --no-packages"
    exit 1
  fi
  MISSING=()
  for p in "${PKGS[@]}"; do
    if pacman -Qq -- "$p" >/dev/null 2>&1; then
      continue                                   # schon installiert
    fi
    if pacman -Si -- "$p" >/dev/null 2>&1; then
      MISSING+=("$p")
    else
      warn "$p ist in den Sync-Datenbanken nicht zu finden — uebersprungen"
    fi
  done
  if (( ${#MISSING[@]} )); then
    echo "  pacman -S --needed: ${MISSING[*]}"
    # Kein "-Sy": ein Teil-Upgrade ist auf Arch der klassische Weg in kaputte
    # Abhaengigkeiten. Wenn die Datenbank zu alt ist, bricht pacman ab und der
    # Hinweis unten sagt, was zu tun ist.
    PAC_FLAGS=(-S --needed)
    (( ASSUME_YES )) && PAC_FLAGS+=(--noconfirm)
    if ! sudo pacman "${PAC_FLAGS[@]}" "${MISSING[@]}"; then
      bad "pacman ist gescheitert — meist eine veraltete Datenbank."
      bad "  sudo pacman -Syu    (voller Upgrade, kein '-Sy' allein!)"
      exit 1
    fi
  else
    ok "Alle Pakete sind bereits installiert"
  fi
fi

# ---------------------------------------------------------------- 3. verify

say "Installation verifizieren"
cd "$ROOT"
VERIFY_RC=0
python3 scripts/verify-install.py || VERIFY_RC=$?
if (( VERIFY_RC )); then
  bad "Pflicht-Abhaengigkeiten fehlen — Autostart/Settings werden nicht geschrieben."
  exit 1
fi

if (( CHECK_ONLY )); then say "Nur Check gewuenscht — fertig."; exit 0; fi

# ---------------------------------------------------------------- 4. monitor

say "Monitor waehlen"
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
    read -r -p "  Connector fuer das Dashboard [auto]: " MONITOR || MONITOR=""
  fi
else
  warn "Konnte die Monitore nicht abfragen — Auto-Erkennung wird verwendet."
fi

if [[ -n "$MONITOR" ]]; then
  KNOWN=0
  while IFS=$'\t' read -r conn _; do
    [[ "$conn" == "$MONITOR" ]] && KNOWN=1
  done <<<"$MONITORS"
  (( KNOWN )) || warn "Connector '$MONITOR' ist gerade nicht angeschlossen — wird trotzdem gespeichert."
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

# ---------------------------------------------------------------- 5. deck

USER_APPS="$HOME/.config/xeneon-edge/apps.json"
if [[ -z "$DECK" ]] && (( IS_OMARCHY )) && [[ ! -e "$USER_APPS" ]] && (( ! ASSUME_YES )); then
  say "Deck vorbelegen"
  echo "  Die mitgelieferten Defaults sind KDE-Kommandos (konsole, dolphin, …)."
  echo "  Fuer Omarchy gibt es eine Variante mit xdg-terminal-exec,"
  echo "  omarchy-launch-browser, nautilus, omarchy-menu, hyprctl reload …"
  read -r -p "  Omarchy-Deck nach $USER_APPS schreiben? [J/n] " ans || ans=""
  [[ "$ans" =~ ^([nN]|nein|no)$ ]] || DECK="omarchy"
elif [[ -z "$DECK" ]] && (( IS_OMARCHY && ASSUME_YES )) && [[ ! -e "$USER_APPS" ]]; then
  DECK="omarchy"
fi

if [[ "$DECK" == "omarchy" ]]; then
  say "Deck vorbelegen"
  if [[ -e "$USER_APPS" ]]; then
    warn "$USER_APPS existiert schon — bleibt unangetastet"
  else
    mkdir -p "$(dirname "$USER_APPS")"
    cp "$ROOT/config/apps.omarchy.json" "$USER_APPS"
    ok "$USER_APPS (aus config/apps.omarchy.json)"
  fi
fi

# ---------------------------------------------------------------- 6. autostart
#
# XDG-Autostart, kein exec-once: uwsm (und damit Omarchy) laesst systemd die
# .desktop-Dateien aus ~/.config/autostart in app-*@autostart.service
# uebersetzen und startet sie mit graphical-session.target. Damit bleibt der
# Schalter "Start with desktop session" im Settings-Modal die einzige Stelle,
# die den Autostart an- und abschaltet — ein zusaetzliches exec-once in
# hyprland.conf wuerde das Dashboard doppelt starten.

if (( AUTOSTART )); then
  say "Autostart einrichten"
  "$ROOT/scripts/install-autostart.sh"
  DESK="$HOME/.config/autostart/xeneon-edge.desktop"
  # Der Repo-Pfad enthaelt ein Leerzeichen — Exec= muss gequotet sein.
  if grep -q '^Exec="' "$DESK" && [[ -x "$ROOT/run.sh" ]]; then
    ok "Exec= korrekt gequotet"
  else
    bad "Exec= in $DESK pruefen (Pfad enthaelt Leerzeichen!)"
  fi
  if command -v hyprctl >/dev/null 2>&1; then
    if systemctl --user list-units --all 'xdg-desktop-autostart.target' 2>/dev/null | grep -q xdg-desktop-autostart; then
      ok "xdg-desktop-autostart.target vorhanden (uwsm startet den Eintrag mit)"
    else
      warn "xdg-desktop-autostart.target nicht gefunden — laeuft Hyprland ohne uwsm?"
      warn "  Dann stattdessen in ~/.config/hypr/autostart.conf:"
      warn "  exec-once = uwsm-app -- \"$ROOT/run.sh\""
    fi
  fi
fi

# ---------------------------------------------------------------- 7. hyprland

if (( DO_HYPR )) && command -v hyprctl >/dev/null 2>&1; then
  say "Hyprland-Fensterregeln"
  HYPR="$HOME/.config/hypr"
  if [[ -f "$HYPR/hyprland.lua" ]]; then
    SNIP="$HYPR/xeneon-edge.lua"
    INCLUDE='require("hypr.xeneon-edge")'
    COMMENT="--"
    HOST="$HYPR/autostart.lua"
    cat > "$SNIP" <<'LUA'
-- Xeneon Edge Dashboard — Hyprland-Regeln
-- Erzeugt von linux/scripts/install-arch.sh; ein erneuter Lauf ueberschreibt
-- die Datei.
--
-- Auf den Zielmonitor legt sich das Dashboard selbst (target_monitor in
-- ~/.config/xeneon-edge/settings.json, fullscreen_on_monitor). Hier stehen nur
-- die Omarchy-Defaults, die ein 2560x720-Streifen nicht will: 0.985 Opacity
-- auf jedem Fenster, Rahmen, Rundungen, Abdunkeln im Hintergrund.
o.window("^(ch\\.xeneon\\.edge)$", {
  tag = "-default-opacity",
  opacity = "1 1",
  border_size = 0,
  rounding = 0,
  no_dim = true,
})

-- Optional: Connector hart pinnen, falls der Vollbild-Wunsch der App mal nicht
-- auf dem richtigen Monitor landet.
-- o.window("^(ch\\.xeneon\\.edge)$", { monitor = "DP-2" })

-- Das TradingView-Login braucht eine Tastatur, am Streifen haengt keine. Auf
-- den richtigen Monitor legt sich das Fenster selbst (find_login_monitor in
-- ui/monitors.py); hier steht nur, dass es schweben soll statt sich in den
-- Workspace zu kacheln.
o.window("^(ch\\.xeneon\\.edge\\.login)$", {
  float = true,
  size = "1400 900",
  center = true,
})
LUA
  else
    SNIP="$HYPR/xeneon-edge.conf"
    INCLUDE="source = ~/.config/hypr/xeneon-edge.conf"
    COMMENT="#"
    HOST="$HYPR/autostart.conf"
    cat > "$SNIP" <<'CONF'
# Xeneon Edge Dashboard — Hyprland-Regeln
# Erzeugt von linux/scripts/install-arch.sh; ein erneuter Lauf ueberschreibt
# die Datei. Syntax: Hyprland 0.53+ (windowrule = <regel>, match:...).
#
# Auf den Zielmonitor legt sich das Dashboard selbst (target_monitor in
# ~/.config/xeneon-edge/settings.json, fullscreen_on_monitor). Hier stehen nur
# die Omarchy-Defaults, die ein 2560x720-Streifen nicht will: 0.985 Opacity auf
# jedem Fenster, Rahmen, Rundungen, Abdunkeln im Hintergrund.
windowrule = tag -default-opacity, match:class ^(ch\.xeneon\.edge)$
windowrule = opacity 1 1,          match:class ^(ch\.xeneon\.edge)$
windowrule = border_size 0,        match:class ^(ch\.xeneon\.edge)$
windowrule = rounding 0,           match:class ^(ch\.xeneon\.edge)$
windowrule = no_dim on,            match:class ^(ch\.xeneon\.edge)$

# Optional: Connector hart pinnen, falls der Vollbild-Wunsch der App mal nicht
# auf dem richtigen Monitor landet.
# windowrule = monitor DP-2, match:class ^(ch\.xeneon\.edge)$

# Das TradingView-Login braucht eine Tastatur, am Streifen haengt keine. Auf den
# richtigen Monitor legt sich das Fenster selbst (find_login_monitor in
# ui/monitors.py); hier steht nur, dass es schweben soll statt sich in den
# Workspace zu kacheln.
windowrule = float,             match:class ^(ch\.xeneon\.edge\.login)$
windowrule = size 1400 900,     match:class ^(ch\.xeneon\.edge\.login)$
windowrule = center,            match:class ^(ch\.xeneon\.edge\.login)$
CONF
  fi
  ok "$SNIP"

  if [[ -f "$HOST" ]]; then
    if grep -qF "xeneon-edge" "$HOST"; then
      ok "$(basename "$HOST") bindet das Snippet bereits ein"
    else
      printf '\n%s Xeneon Edge Dashboard\n%s\n' "$COMMENT" "$INCLUDE" >> "$HOST"
      ok "eingebunden in $HOST"
    fi
  else
    warn "$HOST nicht gefunden — Zeile selbst eintragen:  $INCLUDE"
  fi

  if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    hyprctl reload >/dev/null 2>&1 && ok "hyprctl reload" || warn "hyprctl reload fehlgeschlagen"
  fi
fi

# ---------------------------------------------------------------- 8. summary

say "Fertig"
echo "  Starten:  \"$ROOT/run.sh\""
echo "  Monitor/Apps spaeter aendern:  Zahnrad-Button oben rechts"
if (( IS_OMARCHY )); then
  echo
  echo "  Omarchy-Nachlese:"
  # Wenn nicht gepinnt wurde: den 2560x720-Connector aus der Monitorliste
  # nehmen, damit die Beispielzeile den echten Anschluss nennt.
  EDGE="$MONITOR"
  if [[ -z "$EDGE" && -n "$MONITORS" ]]; then
    EDGE="$(printf '%s\n' "$MONITORS" | awk -F'\t' '/2560x720/ {print $1; exit}')"
  fi
  echo "  · ~/.config/hypr/monitors.conf setzt GDK_SCALE=2 und Monitor-Scale 'auto'."
  echo "    Fuer den Xeneon Edge gehoert dort eine 1x-Zeile hin, z.B.:"
  echo "      monitor = ${EDGE:-DP-2}, 2560x720@60, auto, 1"
  echo "    run.sh erzwingt fuer das Dashboard ohnehin GDK_SCALE=1."
  echo "  · Waybar liegt per Default auf jedem Monitor und frisst ~30px des"
  echo "    720px-Streifens: in ~/.config/waybar/config.jsonc \"output\" auf die"
  echo "    anderen Connectoren begrenzen (oder SUPER+SHIFT+SPACE)."
fi
