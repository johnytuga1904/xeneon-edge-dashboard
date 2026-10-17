# Architecture — configurable modules

Status: steps 1 to 7 are done, and the *Before publishing* list below is
worked off except for the English switch of user-facing strings. The
repository is ready to be made public.

This document describes where the Linux dashboard is going and why. It exists
because the dashboard started as a fixed layout built for one desk — one
monitor, one set of sensors, one football club — and is being turned into
something a stranger can configure without editing Python.

The private Windows (WPF) port this project started from is not covered here.
A macOS port is wanted eventually, which is one reason the configuration
format below is deliberately platform-neutral.

## The problem

`ui/window.py` builds the dashboard in code. Column order is fixed, the three
non-chart column widths are constants (`460 / 420 / 430`), the sensor column
always builds CPU + GPU + RAM + fans, the centre column is TradingView, the
weather is hard-coded to one pair of coordinates and the fixture pill to one
club ID. Every one of those is a reasonable default and a bad law.

## The shape of the answer

Two pieces: a **module registry** that says what can be displayed, and a
**layout file** that says what is displayed, where, and how wide.

### Module registry

Every panel in `ui/panels.py` is already a `Gtk.Box` with `__init__()` and an
`update(data)` method — `CpuPanel`, `RamPanel`, `ProcessPanel`, `AudioPanel`,
all built the same way. That is a module interface in everything but name.
The registry gives it a name and adds the metadata a generic editor needs:

| Field | Purpose |
|-------|---------|
| `type_id` | Stable key used in the layout file (`"sensors"`, `"web"`, …) |
| `label` | Human name, shown in the editor's module catalogue |
| `factory` | `config -> Gtk.Widget`; the widget exposes `update(snapshot)` |
| `needs` | Sensor subsystems the module reads (`{"cpu", "gpu"}`) |
| `schema` | Field descriptions the editor renders settings forms from |
| ↳ `group` | Fields sharing a group render inside one collapsed block |
| ↳ `show_if` | Field appears only when another field holds one of the given values |
| `default_width` | Suggested column width when first placed |

`needs` is what eventually lets the aggregator stop polling what nothing
displays: hide the fan panel and the hwmon reads go away with it. `schema` is
what lets the editor build a settings form for a module it has never heard of,
so adding a module never means touching editor code.

`group` and `show_if` exist because a schema that describes everything a module
*can* do describes more than a user needs to see at once. TradingView is the
case that forced them: seven fields, of which five do nothing when the module
shows an account chart. The rule stays in the module's own declaration rather
than in editor code — the editor only knows how to collapse a group and how to
compare a value.

Modules come in two kinds:

- **Native** — Python/GTK, shipped with the dashboard, cheap and themed like
  everything else. Sensors, processes, audio, launch deck, clock, notes,
  calendar.
- **Web** — a WebKit view pointed at a URL. The user creates these without
  writing any code: a name and an address is the whole definition. This is the
  extension point for everything we did not anticipate. TradingView used to be
  the same module in disguise — an empty URL meant the embedded widget — and is
  now its own module: one asks *where*, the other asks *how*, and a single form
  could not answer both without a field that was inert half the time.

A web module costs a separate WebKit process, roughly 150–300 MB. Views are
therefore created lazily — a tab that is never opened is never instantiated.

Embedding a *native* foreign application (the real Discord client, say) into
the dashboard is not possible under Wayland; there is no XEmbed equivalent and
no compositor trick that gives a normal GTK application someone else's surface.
Such applications belong on the launch deck, which starts them on the main
monitor.

### Layout file

`~/.config/xeneon-edge/layout.json`:

```json
{
  "version": 1,
  "active_profile": "default",
  "profiles": {
    "default": {
      "label": "Standard",
      "columns": [
        { "width": 460,    "modules": [ { "type": "sensors" } ] },
        { "width": "flex", "modules": [ { "type": "web" } ] },
        { "width": 420,    "modules": [ { "type": "processes" }, { "type": "audio" } ] },
        { "width": 430,    "modules": [ { "type": "deck" } ] }
      ],
      "topbar": {
        "weather": { "enabled": true,  "lat": 47.3769, "lon": 8.5417, "label": "Zürich" },
        "match":   { "enabled": false, "league": "eng.1", "team": "359" }
      }
    }
  }
}
```

A column stacks one or more modules vertically, which is how the current
processes-above-audio column is expressed. Exactly one column carries
`"width": "flex"` and absorbs the remaining horizontal space; the editor
enforces that, because a layout with none does not fill the screen and a layout
with two is ambiguous.

Profiles exist so one device can be a trading desk and a media dashboard
without re-arranging anything by hand. They are switched in the editor only —
there is deliberately no on-device switcher.

## Topbar

Since step 4 the topbar is part of the layout: three slots (`left`,
`center`, `right`) holding widgets the same way columns hold modules.
Widgets live in a second registry (`modules.register_topbar`) and are
built in `ui/topbar.py`: brand, sensor status, network, clock, weather,
fixture. Weather and fixture carry their configuration (location, league
and team) and expose it as `feeds`; the aggregator fetches only what a
visible widget asks for and refetches when the config changes. The
action buttons (gear, fullscreen, close) are not in the layout: without
the gear there would be no way back into the editor from the strip.

`layout.json` is version 2 for this. A version-1 file is converted on
load: the old `topbar: {weather, match}` becomes the three slots with
whatever was enabled, so an existing dashboard looks the same after the
update. The shipped default has only the clock in the centre; a location
or a club is not something to ship as a default.

## The editor

Arranging boxes by dragging them is ordinary work in HTML and awkward work in
GTK4, so the editor is a web page, hosted by a small Python script:

```
scripts/layout-editor.py
```

It follows the pattern `scripts/tradingview-login.py` already established: the
dashboard runs fullscreen on a 2560x720 strip that usually has neither keyboard
nor mouse, so anything requiring input opens in an ordinary window on the
*main* monitor instead. `_move_off_dashboard()` moves there and is shared
between the two scripts.

```
Python                                     JavaScript
------                                     ----------
module catalogue + layout.json   ──────▶   render boxes, drag, resize
                                           build settings forms from schema
validate, write layout.json      ◀──────   postMessage(layout)
        │
        ▼
   Gio.FileMonitor  ──▶  dashboard rebuilds, no restart
```

It is opened from the dashboard's own settings (Settings › Layout › *Layout
bearbeiten…*), or directly from a shell. Like the login window it runs in its
own `systemd-run --scope` cgroup, so its WebKit stack is not charged to the
dashboard unit.

The bridge is WebKit's `register_script_message_handler`. The page sends a
JSON string; it is validated in `editor.handle_message` *and* again in
`layout_store.save`, because the page is the one place a layout enters the
system from outside.

The page avoids `prompt()` and `confirm()` entirely — WebKitGTK shows script
dialogs only in some configurations, and a button that silently does nothing
is worse than an ugly one. Profile names are typed into a field that appears
in the header; deleting a profile arms the button for four seconds instead of
asking. The dashboard watches
the file rather than being told directly, which means a layout edited by any
means — the editor, a text editor, a config management tool — takes effect the same way. Modules whose type and config did not change
move from the old grid to the new one instead of being rebuilt; the web view
keeps its page and the deck its state.

The editor is the only settings UI. The gear on the strip launches it on
the main monitor (in its own systemd scope, like the login window). Its
right-hand column shows the settings of whatever is selected: a module's
form built from its `schema`, a topbar widget's form, a column's width, the
deck as a 3×6 grid with per-slot fields, or the global settings (theme,
monitor, autostart, hold-to-confirm, isolated launches, web memory limit).
One *Save* writes `layout.json`, `settings.json` and `apps.json`; the
dashboard watches all three and applies each change live. The former GTK
settings dialog is gone.

Columns are `WeightedColumn` widgets (`ui/layout.py`): modules stacked in a
column get a `height` share in percent, dragged in the editor at the edge
between them. `Gtk.Box` has no weights and a homogeneous `Gtk.Grid` demands
the tallest row's minimum for every row, which pushed the column past the
strip. The process list shows as many rows as fit its share instead of
forcing fourteen. Each deck pad carries its own colour (`accent` in
`apps.json`), painted as the pad's bottom edge through a small runtime CSS
provider; the editor offers a palette behind a colour dot on every pad.

The editor draws **labelled boxes in true proportion**, not a live replica of
the dashboard. A faithful preview would mean maintaining a second rendering of
every panel in HTML, and two renderings of the same thing drift apart. Boxes
cannot drift, and for deciding what goes where they are enough.

Widths are computed twice — by the editor in HTML and by the dashboard in a
`Gtk.Grid` — so they can disagree. The dashboard is authoritative; the editor
shows proportions, never promises pixels.

## Order of work

| Step | Contents | Result |
|------|----------|--------|
| 1 | Registry, `layout.json`, live rebuild, existing panels moved across | Dashboard looks identical, is now file-driven |
| 2 | Status pill reports real sensor source and data age | Fixes a pill that displayed a constant |
| 2b | Colour themes: `themes/*.toml`, `theme.py`, live switch, Omarchy follow-mode | `style.css` carries no colour values any more |
| 2c | Keep unchanged modules across a layout rebuild; wire `needs` into the aggregator | Saving a layout no longer reloads the chart; hidden panels cost nothing |
| 2d | Strip personal defaults, English `README.md`, packaging, CI | Ready to publish |
| 3 | Editor window: boxes, drag, resize, save, profiles | Layout is user-editable |
| 3 | *(done)* Reached via Settings › Layout, or `scripts/layout-editor.py` | |
| 4 | *(done)* Editor is the only settings UI: per-module forms from `schema`, topbar as three slots, deck as 3×6 grid, global settings; GTK dialog removed | Metric selection, web URL + login, weather and fixture config, deck, theme, monitor, autostart |
| 5 | *(done)* Clock with three modes, notes as a read-only file viewer, calendar as a plain month grid | The strip as a clock; a file readable by finger; a month at a glance |
| 6 | *(done)* Now-playing module over MPRIS | Any player — Spotify, YouTube in a browser, mpv — shown and controlled from the strip |
| 7 | *(done)* Own playback of a music folder; TradingView split off from the web module | The strip plays music without a second application; a web panel is a URL and nothing else |
| 8 | *(done)* OpenMarket as a second chart module; the login window takes the site as an argument (`LOGIN_SITES` in `ui/chart.py`) | TradingView, OpenMarket or no chart is a choice in the editor's module list; both charts are picked in the same sign-in window |

Step 1 changes nothing visible on purpose. Everything after it depends on it.

## Themes

A palette is a TOML file with thirteen colours and a `mode` (`dark`/`light`):
window, panel and raised surface; neutral line; text, title and muted text;
accent, warm and hot; text-on-accent; gauge track and edge. `theme.py` turns
it into a `@define-color` block that is loaded in front of `style.css`, which
itself names colours but never states them. Switching is a reload of the one
CSS provider, so it is instant and needs no restart. The one place outside
CSS that paints is the anonymous TradingView widget; it gets background, grid
and light/dark from the same palette. The full chart page brings its own
theme and is left alone.

`omarchy` is a special palette read from the active Omarchy theme's
`colors.toml`. The dashboard watches `~/.local/state/omarchy/current`
(the theme directory is swapped, not edited in place) and recolours itself
when `omarchy-theme-set` runs. The entry is offered only when the file
exists, so on other desktops it is invisible rather than broken. The Windows
renderer uses CSS custom properties with the same names; feeding it the same
TOML files is straightforward but not done.

## Before publishing

Findings from the 2026-09-08 review, in the order they should be done:

- **Done:** `topbar` in `layout.json` is read; weather and fixture are
  topbar widgets that take their coordinates and team from the layout, the
  default profile ships neither, and no coordinates, club IDs or club
  abbreviations remain in code, docs or examples. The chart widget defaults
  to the system time zone (`/etc/localtime`) instead of a fixed one.
- **Done:** `application_id` is `io.github.johnytuga1904.XeneonEdge`
  (`.Login`, `.Editor` for the two helper windows) — the GitHub reverse-DNS
  form that Flatpak and the desktop spec expect for projects without their
  own domain. `install-arch.sh` writes matching Hyprland rules; existing
  installations rerun it (or edit `~/.config/hypr/xeneon-edge.{conf,lua}`).
- **Done (2c):** modules with unchanged type and config survive a layout
  rebuild, so a save no longer reloads the chart. `needs` is wired: the
  aggregator skips CPU, GPU, RAM, fans, processes and audio when no visible
  module wants them, and the sensors module honours `metrics`. Per-tick cost
  before: `nvidia-smi` 28 ms, `pactl` 36 ms every 2 s, `psutil` 20 ms.
  After: NVML 0.1 ms (with `nvidia-smi` fallback), audio read only on a
  `pactl subscribe` event, `FanPanel` keeps a row pool instead of rebuilding
  every second.
- **WebKit is the load.** The account-mode chart costs about 1 GB RSS and
  5 % of a core continuously, and grows over hours (3.7 GB unit peak seen).
  Done: `WebKit.MemoryPressureSettings` on the chart's context
  (`web_memory_limit_mb`, default 1536, measured as process RSS), the web
  process is killed at the limit and the page reloaded three seconds later;
  the same reload path covers a crashed web process, which used to leave the
  panel blank. The login window runs in its own systemd scope so its WebKit
  stack no longer counts against the dashboard unit. The cost is documented
  in the English `README.md` (TradingView section).
- **Done (2026-09-11), repository hygiene:** `pyproject.toml` (version
  from `xeneon_edge.__version__`, ruff config), `.github/workflows/ci.yml`
  (byte-compile + ruff + shell/JS syntax), `CONTRIBUTING.md`, `CHANGELOG.md`, English `README.md`
  with the German text as `README.de.md`. The git history was rewritten with
  `git filter-repo` to drop build outputs, third-party binaries and private
  tooling. The `accent` field in `apps.json` *is* used on Linux (pad colour,
  see step 6) and stays.
- **Still open:** user-facing strings and the editor UI are German
  (`modules/builtin.py` labels and help, tooltips, log lines). A non-German
  user gets a German settings form. This is the last item before a wider
  audience; it is not a blocker for making the repository public.

## Known risks

- **Rebuilding while sensors tick.** The update loop must never hold a
  reference to a widget that has just been torn down. Guarded by rebuilding on
  the GTK main loop and re-reading the module list on every snapshot.
- **Calendar appointments were dropped, and with them the risk.** The plan
  was an `.ics` calendar, whose recurrence rules and timezones are a trap to
  implement by hand and would have taken a dependency. What was actually
  wanted is a month grid — which day of the week the 23rd is — so the module
  shows exactly that and talks to nothing. Should appointments ever come
  back, they belong in a separate module, not bolted onto this one.
- **WebKit memory.** Mitigated by lazy view creation, but a layout full of web
  modules will be heavy and should be expected to be.

## Notes on the modules

The clock also exists as a column module (`ui/clock.py`), so the strip can be
used as a large clock; the topbar keeps its own compact version. Three modes,
chosen in the editor: time with date, time alone, or one row per timezone —
the last one because the strip usually sits next to a chart, and market hours
are what a second clock is for. It paints itself on a `Gtk.DrawingArea`
instead of stacking labels: a font size derived from the allocation also
changes the label's *minimum* size, so the column would re-measure on every
tick and could oscillate between two widths. A drawing area reports no
minimum from its content and may size text to the space it is given.

Notes is read-only by design (`ui/notes.py`). The strip has no keyboard, so a
text editor there would be theatre: the module displays a chosen text,
Markdown or JSON file and reloads it when it changes. JSON is indented on the
way in — a one-line API response is otherwise one unreadable line. Markdown is
*not* rendered: a half-kept promise (headings yes, tables no) is more confusing
than plain text.

It is operated by finger, which is what shapes it. Lines are rows of a
`Gtk.ListBox` inside a `Gtk.ScrolledWindow`, so kinetic scrolling comes from
GTK; rows are a thumb's height rather than a line's; and a tap copies that line
to the clipboard, because without a keyboard that is the only way to get
anything out of the file. The tapped row flashes in the accent colour — a tap
that does nothing visible is indistinguishable from a missed one. The list is
capped at 1500 lines: a `ListBox` builds a widget per row, and a log file with
200'000 lines does not belong on a strip anyway.

The editor gained a `path` field kind for this, with the same file-picker
wiring the deck's command field already used — it opens in `$HOME` instead of
`/usr/bin`.

The calendar (`ui/calendar.py`) is a month grid and nothing else: no
appointments, no account, no network. It answers *which day of the week is the
23rd*, which needs neither a dependency nor a login. Week start and week
numbers are settings. Six week rows are always drawn even when five would do,
because a calendar that changes height between February and March reads as
broken, and today is a filled accent tile rather than merely a different text
colour — on a strip you glance at in passing, it has to carry across the room.

The now-playing module (`ui/mediaplayer.py`, with the D-Bus half in
`sensors/mpris.py`) speaks **MPRIS**, the D-Bus interface essentially every
Linux player implements. Building against it means supporting Spotify,
YouTube in a browser, mpv and VLC at once, instead of picking one. Embedding
a player instead was never an option: Spotify's web player needs Widevine,
which WebKitGTK does not ship, and a video in a 720px column would be a
postage stamp. Heavy applications belong on the main monitor — the strip
shows and controls them.

It reads on signals, not on a clock: `PropertiesChanged` announces track and
play-state changes by itself, and only the playback position has to be
polled, because MPRIS does not report it (`Seeked` fires only on a jump).
That is one D-Bus call per second, and only while something with a known
duration is playing — a live stream reports `2^63-1` as its length, which the
module reads as *no duration* and then draws no progress bar at all.
Transport buttons follow what the player says it can do: the YouTube stream
this was built against reports `CanGoNext: false`, so those buttons are
insensitive rather than lying.

The module resizes itself rather than assuming a shape: title, artist and the
buttons are always there, cover art and the progress bar appear when there is
room. Show and hide thresholds deliberately differ — with a single threshold,
a module sitting exactly on it would flip state on every pass. Two things had
to be learned the hard way here. `do_size_allocate` is never called on a
`Gtk.Box` subclass, because GTK4 hands allocation to the box's layout manager
instead of the widget vfunc (measured: zero calls); the size check therefore
rides the existing one-second tick, which is ample for a size that only
changes when someone saves a layout. And the transport glyphs `⏮ ⏸ ⏭` resolve
to the *emoji* font and come out in colour, which next to a monochrome
interface reads as a mistake — symbolic icon names take the CSS colour and
follow the theme.

The calendar paints itself for the same reason the clock does, and the two share
`ui/drawing.py`: measure once at a reference size, scale by the ratio, since
Pango scales linearly. The one thing to watch there is that a row's font size
must be measured against its *widest* sample — sizing the weekday abbreviations
by `"00"` made "MON TUE WED" run into each other.
