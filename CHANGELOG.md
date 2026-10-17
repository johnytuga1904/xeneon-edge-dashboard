# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project does not
yet use semantic version tags — entries are grouped by date until the first
tagged release.

## [Unreleased]

### Fixed (Linux, 2026-10-17)
- The chart column was black again with WebKit's DMABUF renderer (web
  process alive, page loaded, nothing painted), with and without the Mesa
  pinning. The fallback renderer is the default again, as before September;
  `XENEON_WEBKIT_DMABUF=1` enables DMABUF. Whether the fallback's black
  flashes still occur now that WebKit renders on Mesa is to be measured.
- The sign-in window (`scripts/tradingview-login.py`) stayed blank and took
  no input when its web process ended — seen with the TradingView login
  before, and on the OpenMarket sign-in page nearly every time. The window
  now runs without WebKit's memory-pressure monitor (it lives minutes, see
  the README note on the missing memory cap) and reloads the page when the
  web process ends, up to five times, saying so in the header bar.
- On machines with an AMD/Intel display GPU next to an NVIDIA card, WebKit's
  web process rendered through the NVIDIA EGL driver (GLVND lists it first,
  WebKit takes the first render node) and `libnvidia-eglcore` crashed
  repeatedly. New `xeneon_edge/webkit_env.py` restricts GLVND to the Mesa
  vendor file when both kinds of node exist; dashboard, editor and login
  window apply it before GTK starts. `XENEON_EGL_VENDOR=off|mesa` overrides.

### Fixed (Linux, 2026-09-13)
- SUPER+SHIFT+arrow (Omarchy's `swapwindow`) could swap a work window with the
  dashboard: the dashboard ended up tiled on the main monitor, the window
  behind the strip, and neither `no_focus` nor a `monitor` rule prevents it —
  Hyprland has no way to exempt a monitor from window dispatchers. The Lua
  snippet written by `install-arch.sh` now carries a guard on
  `window.move_to_workspace` / `window.open` (`hl.on`, Hyprland 0.56+) that
  returns the dashboard to the strip with its fullscreen state and sends
  anything else that landed there back to the workspace it came from.

### Fixed (Linux, 2026-09-12)
- The chart column went blank for one or two frames every few minutes — a
  black flash on the strip. Cause was WebKitGTK's shared-memory fallback
  renderer, which `run.sh` had forced (`WEBKIT_DISABLE_DMABUF_RENDERER=1`)
  because of a multi-GPU black column seen under Fedora. The DMABUF renderer
  is the default again (35 minutes of KMS recording without a blank frame);
  `XENEON_WEBKIT_DMABUF=0` restores the fallback for systems that need it.
- The music folder ignored video containers (`.webm`, `.mp4`, `.mkv`, …), so
  a downloaded DJ set left the module at "Keine Musik im Ordner" with a dead
  play button. The player now runs an audio-only GStreamer pipeline instead
  of `Gtk.MediaFile` — which would decode the unseen 4K picture at 70 % of a
  core — and plays the audio track of such files. Debian pulls
  `gir1.2-gstreamer-1.0` instead of `libgtk-4-media-gstreamer`.
- The folder could only be started while no MPRIS player was on the bus at
  all — with two browsers that is never. A fourth button (folder icon, shown
  only when a folder is set) starts and stops it; play keeps belonging to the
  player on screen.
- Playback showed the wrong browser when two reported "Paused" while one of
  them was audibly playing (Brave's MPRIS state can freeze). If no player
  reports "Playing", a short level probe on each open audio stream decides
  which process is actually emitting sound; that player is shown as playing.

### Fixed (Linux, 2026-09-13)
- The TradingView chart froze at its last frame — countdown stopped, web
  process idle — after the page reloaded itself hours into the session. The
  reload was waiting on a TCP connection WebKit had opened over the LAN one
  second before the VPN came up; the tunnel left it silently dead (no RST,
  only retransmits), and the kernel takes ~20 minutes to give up on such a
  socket. Two guards in `ui/chart.py`: a load that shows no content within
  45 s is stopped and retried on a fresh connection, and a network change
  (VPN up or down, Wi-Fi switch) reloads the page after a 5 s settle. Page
  loads now also log when they finish, where they ended up, and why they
  failed — before, only the start was logged, so a hung reload was
  indistinguishable from a frozen renderer.

### Changed
- Linux: application id is `io.github.johnytuga1904.XeneonEdge` (helper
  windows: `.Login`, `.Editor`) instead of `ch.xeneon.edge`. Existing
  installations rerun `install-arch.sh` or update the class regexes in
  `~/.config/hypr/xeneon-edge.{conf,lua}`.
- Linux: the TradingView widget defaults to the system time zone
  (`/etc/localtime`) instead of a fixed one.
- Repository: build outputs, third-party binaries and private tooling were
  removed from the whole git history (37 MB → 0.4 MB pack). Clones made
  before 2026-09-11 do not share history with the current `master`.

### Added
- Linux: *Zoom* setting for the web panel and the OpenMarket module (page
  zoom, 50–150 %; OpenMarket defaults to 72 % so its order book, total
  column included, fits the centre column).
- Linux: OpenMarket (openmarket.xyz) as a second chart module next to
  TradingView — your own chart from the account, chosen through the same
  sign-in window (`scripts/tradingview-login.py --site openmarket`, writes
  `openmarket_url`). Measured at ~1 GB RSS and ~30 % of a core; documented in
  the Linux README.
- `pyproject.toml`, `CONTRIBUTING.md`, this changelog, an English
  `README.md` (German text kept as `README.de.md`) and a GitHub Actions
  workflow that byte-compiles and lints the code.
- Repository: the Linux port moved into its own repository (2026-10-18,
  `git subtree split`); the frozen Windows/WPF port stays private.

### Fixed (Linux, 2026-09-11 review)
- Weather and fixture pills stayed empty for the first 10 / 60 minutes after
  boot (fetch timestamp compared against `time.monotonic()` starting at 0).
- Without an AMD or NVIDIA GPU the placeholder panel was rebuilt every second.
- The `label` palette colour never applied (`@label_color` vs `@label`).
- Missing GTK media backend was not detected (`GtkNoMediaFile`); the local
  music player cycled through every file logging an error. Debian installer
  now pulls `libgtk-4-media-gstreamer`.
- A playback module replaced through the editor kept its D-Bus subscription
  and its audio stream alive.
- A `settings.json` or `apps.json` whose top level was not an object
  terminated the dashboard before the first window.
- Hold-to-confirm on dangerous deck pads fired after 300 ms instead of ~1 s.
- Closing the TradingView login window without confirming switched the
  module to account mode anyway.
- If `pactl subscribe` failed once at autostart, audio fell back to polling
  for the rest of the session.
- WebKit profile directories (TradingView session cookies) are created 0700.
- Fixture day label off by one after local midnight; ISO week number wrong
  for Sunday-start weeks; hard-coded "DDR5" in the RAM panel; AMD power on
  RDNA3 (`power1_input`); process module could show 20 rows but received 14.

## 2026-09-01 … 2026-09-10 — first version

- GTK4/Python port with sensors from `/proc` and `/sys`, AMD and NVIDIA GPUs
  side by side, hwmon fans, PipeWire audio, 3×6 launch deck with
  `systemd-run` isolation.
- Layout from `layout.json` (profiles, columns, topbar slots) with a
  WebKit-based layout editor; modules survive a rebuild when unchanged.
- Modules: sensors, processes, audio, deck, web panel, TradingView (widget or
  account chart with memory cap and crash reload), clock, calendar, notes,
  playback (MPRIS or a local music folder).
- Five colour themes plus one that follows the active Omarchy palette.
- Installers for Arch/Omarchy and Debian 13, Hyprland window rules,
  Omarchy notification patch.
