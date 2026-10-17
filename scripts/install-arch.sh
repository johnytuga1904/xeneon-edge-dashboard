#!/usr/bin/env bash
# Installer for Arch Linux and Arch derivatives — tested against Omarchy
# (Arch + Hyprland + uwsm).
#
#   ./scripts/install-arch.sh [options]
#
#   --no-autostart      skip the ~/.config/autostart entry
#   --monitor NAME      pin the dashboard to a DRM connector (e.g. DP-2)
#   --no-fullscreen     don't fullscreen on the target monitor
#   --deck omarchy      prefill the Launch Deck with Omarchy commands (only
#                       when ~/.config/xeneon-edge/apps.json does not exist yet)
#   --no-hypr           skip the Hyprland snippet (window rules)
#   --yes               never ask anything (uses auto-detect for the monitor)
#   --no-packages       skip pacman entirely (only write settings/autostart)
#   --check             only verify, install nothing
#
# Package names are the ones from [core]/[extra]; everything is in the official
# repos, no AUR helper needed. Python deps come from pacman, not from
# requirements.txt: Arch marks its Python as externally managed (PEP 668), so
# "pip install --user" aborts with an externally-managed-environment error.
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

say "Checking the system"
if [[ ! -r /etc/os-release ]]; then
  bad "/etc/os-release is missing — not Arch?"; exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
echo "  ${PRETTY_NAME:-?}  (ID=${ID:-?})"
case "${ID:-}:${ID_LIKE:-}" in
  arch:*|*:*arch*) ;;
  *) warn "Not Arch or an Arch derivative — package names may differ." ;;
esac

IS_OMARCHY=0
OMARCHY_DIR="${OMARCHY_PATH:-$HOME/.local/share/omarchy}"
if [[ -d "$OMARCHY_DIR" ]] || command -v omarchy-menu >/dev/null 2>&1; then
  IS_OMARCHY=1
  OMV="$(command -v omarchy-version >/dev/null 2>&1 && omarchy-version 2>/dev/null || true)"
  ok "Omarchy detected${OMV:+ ($OMV)}"
fi
if command -v hyprctl >/dev/null 2>&1; then
  ok "Hyprland: $(hyprctl version -j 2>/dev/null | sed -n 's/.*"tag": *"\([^"]*\)".*/\1/p' | head -1 || echo "?")"
fi
[[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] || warn "No display session — the GUI parts will not run here."

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
  warn "NVIDIA card, but no nvidia-smi — it comes with 'nvidia-utils'"
  warn "  (on Omarchy: set up the driver with 'omarchy-install-nvidia')"
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
  gst-plugins-good      # autoaudiosink — sonst bricht WebKit beim Login ab
  pciutils              # lspci (GPU-Erkennung)
  adwaita-icon-theme    # Icon-Fallbacks im Deck
  xdg-desktop-portal-gtk # Datei-Picker im Settings-Dialog unter Wayland
)
# NVML-Bindings: NVIDIA-Werte in-process (0,1 ms) statt nvidia-smi als
# Prozessstart pro Tick (28 ms). Haengt nicht am Treiberpaket, kann also
# mit installiert werden; ohne Treiber faellt das Dashboard auf nvidia-smi zurueck.
if (( HAS_NVIDIA )); then PKGS+=(python-nvidia-ml-py); fi

if (( ! CHECK_ONLY && DO_PACKAGES )); then
  say "Installing packages"
  if ! command -v pacman >/dev/null 2>&1; then
    bad "pacman not found — this script needs Arch."
    bad "To only write settings + autostart: $0 --no-packages"
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
      warn "$p is not in the sync databases — skipped"
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
      bad "pacman failed — usually an outdated database."
      bad "  sudo pacman -Syu    (full upgrade, never '-Sy' alone!)"
      exit 1
    fi
  else
    ok "All packages are already installed"
  fi
fi

# ---------------------------------------------------------------- 3. verify

say "Verifying the installation"
cd "$ROOT"
VERIFY_RC=0
python3 scripts/verify-install.py || VERIFY_RC=$?
if (( VERIFY_RC )); then
  bad "Required dependencies are missing — autostart/settings will not be written."
  exit 1
fi

if (( CHECK_ONLY )); then say "Check only — done."; exit 0; fi

# ---------------------------------------------------------------- 4. monitor

say "Choosing the monitor"
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
    echo "  Leave empty = auto-detect (looks for a 2560x720 monitor)."
    read -r -p "  Connector for the dashboard [auto]: " MONITOR || MONITOR=""
  fi
else
  warn "Could not query the monitors — auto-detect will be used."
fi

if [[ -n "$MONITOR" ]]; then
  KNOWN=0
  while IFS=$'\t' read -r conn _; do
    [[ "$conn" == "$MONITOR" ]] && KNOWN=1
  done <<<"$MONITORS"
  (( KNOWN )) || warn "Connector '$MONITOR' is not connected right now — saving it anyway."
fi

say "Writing settings.json"
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
  say "Prefilling the Launch Deck"
  echo "  The bundled defaults are KDE commands (konsole, dolphin, …)."
  echo "  For Omarchy there is a variant with xdg-terminal-exec,"
  echo "  omarchy-launch-browser, nautilus, omarchy-menu, hyprctl reload …"
  read -r -p "  Write the Omarchy deck to $USER_APPS? [Y/n] " ans || ans=""
  [[ "$ans" =~ ^([nN]|no)$ ]] || DECK="omarchy"
elif [[ -z "$DECK" ]] && (( IS_OMARCHY && ASSUME_YES )) && [[ ! -e "$USER_APPS" ]]; then
  DECK="omarchy"
fi

if [[ "$DECK" == "omarchy" ]]; then
  say "Prefilling the Launch Deck"
  if [[ -e "$USER_APPS" ]]; then
    warn "$USER_APPS already exists — left untouched"
  else
    mkdir -p "$(dirname "$USER_APPS")"
    cp "$ROOT/config/apps.omarchy.json" "$USER_APPS"
    ok "$USER_APPS (from config/apps.omarchy.json)"
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
  say "Setting up autostart"
  "$ROOT/scripts/install-autostart.sh"
  DESK="$HOME/.config/autostart/xeneon-edge.desktop"
  # Der Repo-Pfad enthaelt ein Leerzeichen — Exec= muss gequotet sein.
  if grep -q '^Exec="' "$DESK" && [[ -x "$ROOT/run.sh" ]]; then
    ok "Exec= is quoted correctly"
  else
    bad "Check Exec= in $DESK (the path contains a space!)"
  fi
  if command -v hyprctl >/dev/null 2>&1; then
    if systemctl --user list-units --all 'xdg-desktop-autostart.target' 2>/dev/null | grep -q xdg-desktop-autostart; then
      ok "xdg-desktop-autostart.target present (uwsm starts the entry)"
    else
      warn "xdg-desktop-autostart.target not found — is Hyprland running without uwsm?"
      warn "  Then put this in ~/.config/hypr/autostart.conf instead:"
      warn "  exec-once = uwsm-app -- \"$ROOT/run.sh\""
    fi
  fi
fi

# ---------------------------------------------------------------- 7. hyprland

if (( DO_HYPR )) && command -v hyprctl >/dev/null 2>&1; then
  say "Hyprland window rules"
  HYPR="$HOME/.config/hypr"
  if [[ -f "$HYPR/hyprland.lua" ]]; then
    SNIP="$HYPR/xeneon-edge.lua"
    INCLUDE='require("hypr.xeneon-edge")'
    COMMENT="--"
    HOST="$HYPR/autostart.lua"
    cat > "$SNIP" <<'LUA'
-- Xeneon Edge Dashboard — Hyprland rules
-- Written by scripts/install-arch.sh; running it again overwrites this file.
--
-- The dashboard places itself on the target monitor (target_monitor in
-- ~/.config/xeneon-edge/settings.json, fullscreen_on_target). This file only
-- undoes the Omarchy defaults a 2560x720 strip does not want: 0.985 opacity
-- on every window, borders, rounded corners, dimming in the background.
--
-- no_focus: the strip is a display, not a workplace. Without the rule,
-- SUPER+arrow moves the focus there and the dashboard becomes the active
-- window. It is operated by touch, and touch and pointer events go to the
-- surface under the finger, not to the focused window — the deck buttons
-- keep working.
o.window("^(io\\.github\\.johnytuga1904\\.XeneonEdge)$", {
  tag = "-default-opacity",
  opacity = "1 1",
  border_size = 0,
  rounding = 0,
  no_dim = true,
  no_focus = true,
})

-- Optional: pin the connector hard, in case the app's fullscreen request ever
-- lands on the wrong monitor. The connector name differs from machine to
-- machine, so this is only an example — and it belongs in a file this script
-- does not overwrite.
-- o.window("^(io\\.github\\.johnytuga1904\\.XeneonEdge)$", { monitor = "DP-2" })

-- Guard: the dashboard stays on the strip, and nothing else ends up there.
--
-- no_focus and monitor= are not enough for that. monitor= only applies when
-- a window opens, and Omarchy's SUPER+SHIFT+arrow (swapwindow) needs no
-- focus on the dashboard: it swaps the active window with the next one in
-- that direction, and for that the dashboard is a window like any other.
-- The strip usually sits below or next to the main monitor — a swap
-- downwards tiles the dashboard into the work workspace and puts the swapped
-- window behind the strip. Hyprland has no switch that exempts a monitor
-- from window dispatchers.
--
-- So the mess is cleaned up afterwards: every workspace change of a window
-- goes through CWindow::moveToWorkspace and fires window.move_to_workspace,
-- for swaps and for drags with the mouse alike. The strip is the monitor
-- from target_monitor in ~/.config/xeneon-edge/settings.json, otherwise the
-- one with 2560x720; without either the guard does nothing.
--
-- The cleanup is idempotent: it looks at all windows instead of the one from
-- the event, because a swap delivers two events in no guaranteed order. And
-- it runs one tick later, so the dispatcher that triggered it has finished
-- before new ones are started here.
local DASHBOARD_CLASS = "io.github.johnytuga1904.XeneonEdge"
local SETTINGS = (os.getenv("HOME") or "") .. "/.config/xeneon-edge/settings.json"

local function is_dashboard(w)
  return w.class == DASHBOARD_CLASS
end

-- The strip's connector. The settings are read on every run so a change in
-- the editor takes effect without a reload; this only happens on window
-- moves, not on a timer.
local function strip_monitor()
  local monitors = hl.get_monitors()
  local f = io.open(SETTINGS, "r")
  if f then
    local text = f:read("a") or ""
    f:close()
    local wanted = text:match('"target_monitor"%s*:%s*"([^"]+)"')
    if wanted then
      for _, m in ipairs(monitors) do
        if m.name == wanted then return m end
      end
    end
  end
  for _, m in ipairs(monitors) do
    if m.width == 2560 and m.height == 720 then return m end
  end
  return nil
end

local function on_strip(w, strip)
  return w.monitor ~= nil and w.monitor.name == strip.name
end

-- The fullscreen state the dashboard last had on the strip. A move throws
-- the fullscreen away; after bringing it back, exactly this state is set
-- again — not blindly 2, so fullscreen_on_target=false stays respected.
-- Until the first look, the app's default applies: fullscreen.
local edge_fullscreen = 2

-- Last workspace away from the strip, per window. The event only names the
-- destination of a move, not the origin — so it is recorded as long as the
-- destination is not the strip.
local last_home = {}

local function remember_home(w, ws)
  local strip = strip_monitor()
  if ws and ws.monitor and not (strip and ws.monitor.name == strip.name) then
    last_home[w.address] = ws.id
  end
end

-- Where a foreign window that landed on the strip belongs: where it was
-- last. Without a record — e.g. right after a reload — on a swap to where
-- the dashboard is now, otherwise to the workspace of the focused monitor
-- unless that is the strip, and as a last resort to any monitor except the
-- strip.
local function home_workspace(w, strip)
  local remembered = last_home[w.address] and hl.get_workspace(last_home[w.address])
  if remembered and remembered.monitor and remembered.monitor.name ~= strip.name then
    return remembered
  end
  for _, w in ipairs(hl.get_windows()) do
    if is_dashboard(w) and w.workspace and not on_strip(w, strip) then
      return w.workspace
    end
  end
  local active = hl.get_active_monitor()
  if active and active.name ~= strip.name and active.active_workspace then
    return active.active_workspace
  end
  for _, m in ipairs(hl.get_monitors()) do
    if m.name ~= strip.name and m.active_workspace then
      return m.active_workspace
    end
  end
  return nil
end

local function settle()
  local strip = strip_monitor()
  if not strip then return end

  -- First move the strangers off the strip: home_workspace() reads where the
  -- dashboard is right now, so it must not have been pulled back yet.
  for _, w in ipairs(hl.get_windows()) do
    if not is_dashboard(w) and w.mapped and on_strip(w, strip) then
      local home = home_workspace(w, strip)
      if home then
        -- The active window takes the focus back with it, otherwise the
        -- focus would be stuck on the strip; everything else moves quietly.
        hl.dispatch(hl.dsp.window.move({ window = w, workspace = home.id, follow = w.active }))
      end
    end
  end

  for _, w in ipairs(hl.get_windows()) do
    if is_dashboard(w) and w.mapped and w.workspace then
      if on_strip(w, strip) then
        edge_fullscreen = w.fullscreen
      else
        hl.dispatch(hl.dsp.window.move({ window = w, monitor = strip.name, follow = false }))
        if edge_fullscreen > 0 then
          hl.dispatch(hl.dsp.window.fullscreen_state({
            window = w, internal = edge_fullscreen, client = edge_fullscreen,
          }))
        end
      end
    end
  end
end

-- Several events in quick succession (a swap delivers two) result in a
-- single cleanup run.
local pending = false
local function schedule_settle()
  if pending then return end
  pending = true
  hl.timer(function()
    pending = false
    settle()
  end, { timeout = 1, type = "oneshot" })
end

-- Older Lua Hyprlands may not know the events; then the rules above still
-- apply instead of the whole config falling apart.
local subscribed = pcall(function()
  hl.on("window.move_to_workspace", function(w, ws)
    remember_home(w, ws)
    schedule_settle()
  end)
  -- New windows go to the focused workspace — and that is the strip when
  -- SUPER+arrow landed there or a deck button started something by touch.
  hl.on("window.open", function(w)
    remember_home(w, w.workspace)
    schedule_settle()
  end)
  -- Clean up on window.close, not window.destroy: at destroy the window is
  -- already torn down and w.address is nil — last_home[nil] = nil is a Lua
  -- runtime error ("table index is nil") that ended up in the error overlay
  -- every time a window closed. At close the address is still there; the
  -- guard catches the rest.
  hl.on("window.close", function(w)
    local addr = w and w.address
    if addr then last_home[addr] = nil end
  end)
end)
if not subscribed then
  hl.notification.create({
    text = "Xeneon Edge: Hyprland without Lua events, dashboard guard disabled",
    timeout = 8000, icon = "warning",
  })
end

-- The TradingView sign-in needs a keyboard, and the strip has none. The
-- window places itself on the right monitor (find_login_monitor in
-- ui/monitors.py); this only says it should float instead of tiling into
-- the workspace.
o.window("^(io\\.github\\.johnytuga1904\\.XeneonEdge\\.Login)$", {
  float = true,
  size = "1400 900",
  center = true,
})

-- The layout editor needs a keyboard as well and sits on the main monitor
-- for the same reason. Without its own rule it would get Omarchy's default
-- transparency — judging colours through an editor that shows the desktop
-- underneath is impossible.
o.window("^(io\\.github\\.johnytuga1904\\.XeneonEdge\\.Editor)$", {
  tag = "-default-opacity",
  opacity = "1 1",
  float = true,
  size = "1800 640",
  center = true,
})
LUA
  else
    SNIP="$HYPR/xeneon-edge.conf"
    INCLUDE="source = ~/.config/hypr/xeneon-edge.conf"
    COMMENT="#"
    HOST="$HYPR/autostart.conf"
    cat > "$SNIP" <<'CONF'
# Xeneon Edge Dashboard — Hyprland rules
# Written by scripts/install-arch.sh; running it again overwrites this file.
# Syntax: Hyprland 0.53+ (windowrule = <rule>, match:...).
#
# The dashboard places itself on the target monitor (target_monitor in
# ~/.config/xeneon-edge/settings.json, fullscreen_on_target). This file only
# undoes the Omarchy defaults a 2560x720 strip does not want: 0.985 opacity on
# every window, borders, rounded corners, dimming in the background.
#
# no_focus: the strip is a display, not a workplace. Without the rule,
# SUPER+arrow moves the focus there and the dashboard becomes the active
# window. It is operated by touch, and touch and pointer events go to the
# surface under the finger, not to the focused window — the deck buttons
# keep working.
#
# What is missing here: the guard from the Lua version that brings the
# dashboard back to the strip after a swapwindow (SUPER+SHIFT+arrow). It
# needs the event API of the Lua config (hl.on); in the classic config all
# that remains is to avoid the strip when swapping.
windowrule = tag -default-opacity, match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$
windowrule = opacity 1 1,          match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$
windowrule = border_size 0,        match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$
windowrule = rounding 0,           match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$
windowrule = no_dim on,            match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$
windowrule = no_focus on,          match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$

# Optional: pin the connector hard, in case the app's fullscreen request ever
# lands on the wrong monitor, or a dispatcher moves it after all. The
# connector name differs from machine to machine, so this is only an example
# — and it belongs in a file this script does not overwrite.
# windowrule = monitor DP-2, match:class ^(io\.github\.johnytuga1904\.XeneonEdge)$

# The TradingView sign-in needs a keyboard, and the strip has none. The window
# places itself on the right monitor (find_login_monitor in ui/monitors.py);
# this only says it should float instead of tiling into the workspace.
windowrule = float,             match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Login)$
windowrule = size 1400 900,     match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Login)$
windowrule = center,            match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Login)$

# The layout editor needs a keyboard as well. Without its own rule it would
# get the default transparency — judging colours through an editor that shows
# the desktop underneath is impossible.
windowrule = opacity 1 1,       match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Editor)$
windowrule = float,             match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Editor)$
windowrule = size 1800 640,     match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Editor)$
windowrule = center,            match:class ^(io\.github\.johnytuga1904\.XeneonEdge\.Editor)$
CONF
  fi
  ok "$SNIP"

  if [[ -f "$HOST" ]]; then
    if grep -qF "xeneon-edge" "$HOST"; then
      ok "$(basename "$HOST") already includes the snippet"
    else
      printf '\n%s Xeneon Edge Dashboard\n%s\n' "$COMMENT" "$INCLUDE" >> "$HOST"
      ok "included in $HOST"
    fi
  else
    warn "$HOST not found — add this line yourself:  $INCLUDE"
  fi

  if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    hyprctl reload >/dev/null 2>&1 && ok "hyprctl reload" || warn "hyprctl reload failed"
  fi
fi

# ---------------------------------------------------------------- 8. summary

say "Done"
echo "  Start:  \"$ROOT/run.sh\""
echo "  Change monitor/apps later:  gear button at the top right"
if (( IS_OMARCHY )); then
  echo
  echo "  Omarchy follow-up:"
  # Wenn nicht gepinnt wurde: den 2560x720-Connector aus der Monitorliste
  # nehmen, damit die Beispielzeile den echten Anschluss nennt.
  EDGE="$MONITOR"
  if [[ -z "$EDGE" && -n "$MONITORS" ]]; then
    EDGE="$(printf '%s\n' "$MONITORS" | awk -F'\t' '/2560x720/ {print $1; exit}')"
  fi
  echo "  · ~/.config/hypr/monitors.conf sets GDK_SCALE=2 and monitor scale 'auto'."
  echo "    The Xeneon Edge needs a 1x line there, e.g.:"
  echo "      monitor = ${EDGE:-DP-2}, 2560x720@60, auto, 1"
  echo "    run.sh forces GDK_SCALE=1 for the dashboard anyway."
  echo "  · Waybar sits on every monitor by default and eats ~30px of the"
  echo "    720px strip: limit \"output\" in ~/.config/waybar/config.jsonc to the"
  echo "    other connectors (or SUPER+SHIFT+SPACE)."
fi
