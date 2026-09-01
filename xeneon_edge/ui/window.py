"""Main window: topbar + 3-column grid (sensor stack, chart, right stack) + deck."""
from __future__ import annotations
from datetime import datetime, timezone
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib  # noqa: E402

from .panels import CpuPanel, GpuPanel, RamPanel, ProcessPanel, FanPanel
from .audio_panel import AudioPanel
from .deck import LaunchDeck
from .chart import make_chart_widget
from .layout import FixedWidth
from .. import config_store

# Column widths in px. These are hard, not minimums: FixedWidth reports them as
# both minimum and natural, so no value inside a column can ever move it.
# The chart column carries no fixed width — it absorbs whatever is left over,
# which is the only thing that adapts the layout to a different screen.
COL_SENSORS_W = 460
COL_PROCS_W = 420
COL_DECK_W = 430


def _pin(label: Gtk.Label, chars: int) -> Gtk.Label:
    """Reserve exactly ``chars`` — minimum and natural width become identical."""
    label.set_width_chars(chars)
    label.set_max_width_chars(chars)
    label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
    return label


def _fmt_speed(mbps: float) -> tuple[str, str]:
    """Pretty-format throughput from megabits/sec to a (value, unit) tuple."""
    # bytes/sec = mbps * 1_000_000 / 8 → divide by 1024 for KiB/s scale
    bps = max(0.0, mbps * 125_000)  # bytes per second
    if bps < 1024:
        return f"{bps:.0f}", "B/s"
    kib = bps / 1024
    if kib < 1024:
        return (f"{kib:.0f}" if kib >= 10 else f"{kib:.1f}"), "KB/s"
    mib = kib / 1024
    if mib < 1024:
        return (f"{mib:.1f}" if mib < 10 else f"{mib:.0f}"), "MB/s"
    return f"{mib/1024:.2f}", "GB/s"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, *, on_open_settings):
        super().__init__(application=app)
        self.set_default_size(1480, 900)
        self.set_title("Xeneon Edge Dashboard")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(6); outer.set_margin_bottom(6)
        outer.set_margin_start(6); outer.set_margin_end(6)
        self.set_content(outer)

        # ----- Topbar -----
        # CenterBox guarantees the center slot is exactly centered relative to
        # the window, regardless of how wide the start/end slots get.
        topbar = Gtk.CenterBox()
        topbar.set_hexpand(True)
        outer.append(topbar)

        # left brand
        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        brand_label = Gtk.Label(xalign=0)
        brand_label.set_markup(
            '<span weight="900" letter_spacing="2400">XENEON</span>'
            '<span foreground="#ff0033" weight="900">//</span>'
            '<span weight="900" letter_spacing="2400">EDGE</span>'
        )
        brand_label.add_css_class("brand")
        sub = Gtk.Label(label="COMMAND CENTER", xalign=0)
        sub.add_css_class("brand-sub")
        brand_box.append(brand_label); brand_box.append(sub)

        status_pill = self._make_pill()
        self.sensor_status = _pin(Gtk.Label(label="Sensors warming up", xalign=0), 21)
        self.sensor_status.add_css_class("pill-text")
        status_pill.append(self.sensor_status)

        net_pill = self._make_pill()
        net_pill.set_spacing(8)
        # Fixed char reserves — "1.2" → "123.4" and "KB/s" → "MB/s" must not
        # resize the pill (and with it the whole topbar) as traffic changes.
        d_arrow = Gtk.Label(label="↓"); d_arrow.add_css_class("arrow")
        self.net_down = _pin(Gtk.Label(label="--", xalign=1), 5); self.net_down.add_css_class("pill-strong")
        self.net_down_unit = _pin(Gtk.Label(label="KB/s", xalign=0), 7); self.net_down_unit.add_css_class("pill-text")
        u_arrow = Gtk.Label(label="↑"); u_arrow.add_css_class("arrow")
        self.net_up = _pin(Gtk.Label(label="--", xalign=1), 5); self.net_up.add_css_class("pill-strong")
        self.net_up_unit = _pin(Gtk.Label(label="KB/s", xalign=0), 7); self.net_up_unit.add_css_class("pill-text")
        for w in (d_arrow, self.net_down, self.net_down_unit, u_arrow, self.net_up, self.net_up_unit):
            net_pill.append(w)

        # ---- Topbar START slot: brand + status + net pills
        start_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        start_strip.append(brand_box)
        start_strip.append(status_pill)
        start_strip.append(net_pill)
        topbar.set_start_widget(start_strip)

        # ---- Topbar CENTER slot: weather + clock + match (clock truly in middle)
        center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        center.set_halign(Gtk.Align.CENTER)

        weather_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        weather_box.add_css_class("panel"); weather_box.add_css_class("topbar-pill")
        self.weather_symbol = Gtk.Label(label="--"); self.weather_symbol.add_css_class("weather-symbol")
        self.weather_temp = _pin(Gtk.Label(label="--", xalign=1), 5)
        self.weather_temp.add_css_class("weather-temp-strong")
        weather_unit = Gtk.Label(label="°C"); weather_unit.add_css_class("weather-temp")
        weather_box.append(self.weather_symbol); weather_box.append(self.weather_temp); weather_box.append(weather_unit)

        clock_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        clock_box.set_halign(Gtk.Align.CENTER)
        self.clock_time = Gtk.Label(label="00:00", xalign=0.5); self.clock_time.add_css_class("clock-time")
        self.clock_date = _pin(Gtk.Label(label="--", xalign=0.5), 15)
        self.clock_date.add_css_class("clock-date")
        clock_box.append(self.clock_time); clock_box.append(self.clock_date)

        # SLB match widget (right of clock)
        match_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        match_box.add_css_class("panel"); match_box.add_css_class("topbar-pill"); match_box.add_css_class("match-widget")
        slb_label = Gtk.Label(label="SLB"); slb_label.add_css_class("match-team")
        match_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.match_opponent = Gtk.Label(label="--", xalign=0); self.match_opponent.add_css_class("match-opponent")
        _pin(self.match_opponent, 19)
        self.match_when = _pin(Gtk.Label(label="--", xalign=0), 22)
        self.match_when.add_css_class("match-when")
        match_text.append(self.match_opponent); match_text.append(self.match_when)
        match_box.append(slb_label); match_box.append(match_text)
        match_box.set_tooltip_text("Next SL Benfica match")
        self.match_box = match_box

        center.append(weather_box); center.append(clock_box); center.append(match_box)
        topbar.set_center_widget(center)

        # ---- Topbar END slot: window actions
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_btn = Gtk.Button(label="⚙"); settings_btn.add_css_class("ico")
        settings_btn.connect("clicked", lambda *_: on_open_settings())
        fs_btn = Gtk.Button(label="FS"); fs_btn.add_css_class("ico")
        fs_btn.connect("clicked", self._toggle_fullscreen)
        close_btn = Gtk.Button(label="X"); close_btn.add_css_class("ico"); close_btn.add_css_class("danger")
        close_btn.connect("clicked", lambda *_: self.close())
        actions.append(settings_btn); actions.append(fs_btn); actions.append(close_btn)
        topbar.set_end_widget(actions)

        # ----- Main grid: single row, 4 columns side-by-side -----
        # Layout for 2560x720 Xeneon Edge:
        #   [ Sensors | Chart | Procs+Audio | Launch Deck ]
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.set_hexpand(True); grid.set_vexpand(True)
        outer.append(grid)
        grid.set_column_homogeneous(False)

        # Col 0: Sensors stack — narrow, panels stretched to fill column height
        sensors_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sensors_col.set_vexpand(True)
        sensors_col.set_hexpand(False)  # don't compete with chart for width
        sensors_col.add_css_class("col-sensors")
        self.cpu_panel = CpuPanel()
        self.gpu_panels: list[GpuPanel] = []
        self.gpu_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.gpu_container.set_vexpand(True)
        self.ram_panel = RamPanel()
        self.fan_panel = FanPanel()
        for w in (self.cpu_panel, self.gpu_container, self.ram_panel, self.fan_panel):
            w.set_vexpand(True)
        sensors_col.append(self.cpu_panel)
        sensors_col.append(self.gpu_container)
        sensors_col.append(self.ram_panel)
        sensors_col.append(self.fan_panel)
        grid.attach(FixedWidth(sensors_col, COL_SENSORS_W), 0, 0, 1, 1)

        # Col 1: Chart — flexes to take all remaining horizontal space.
        # chart_url leer = eingebettetes Widget; eine URL laedt die echte
        # TradingView-Seite mit der gespeicherten Session (Login siehe
        # scripts/tradingview-login.py). Der Halter bleibt in der Grid-Zelle
        # stehen, damit set_chart_url() nur sein Kind tauschen muss.
        self._chart_url = config_store.load_settings().get("chart_url", "") or ""
        self.chart_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.chart_holder.set_hexpand(True)
        self.chart_holder.set_vexpand(True)
        self.chart_holder.append(make_chart_widget(self._chart_url))
        grid.attach(self.chart_holder, 1, 0, 1, 1)

        # Col 2: Top processes (stretches) + Audio (fixed at bottom)
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right_col.set_vexpand(True)
        right_col.set_hexpand(False)
        right_col.add_css_class("col-compact")
        self.process_panel = ProcessPanel()
        self.process_panel.set_vexpand(True)
        self.process_panel.set_hexpand(False)
        self.audio_panel = AudioPanel()
        self.audio_panel.set_hexpand(False)
        right_col.append(self.process_panel)
        right_col.append(self.audio_panel)
        grid.attach(FixedWidth(right_col, COL_PROCS_W), 2, 0, 1, 1)

        # Col 3: Launch Deck — 3 cols × 6 rows, fixed width, fills full column height
        self.deck = LaunchDeck()
        self.deck.set_vexpand(True)
        self.deck.set_hexpand(False)
        grid.attach(FixedWidth(self.deck, COL_DECK_W), 3, 0, 1, 1)

        # tick the clock every second
        self._update_clock()
        GLib.timeout_add_seconds(1, self._update_clock)

    def _make_pill(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.add_css_class("pill")
        return box

    def _toggle_fullscreen(self, *_args) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _update_clock(self) -> bool:
        now = datetime.now()
        self.clock_time.set_label(now.strftime("%H:%M"))
        self.clock_date.set_label(now.strftime("%A").upper())
        return True

    # ----- snapshot push -----

    def apply_snapshot(self, snap) -> None:
        self.cpu_panel.update(snap.cpu, snap.cpu_name)
        self.ram_panel.update(snap.ram)
        self.process_panel.update(snap.processes)
        self.fan_panel.update(snap.fans)
        self.audio_panel.update(snap.audio)

        # GPU panels: rebuild count if it changed
        if len(self.gpu_panels) != len(snap.gpus):
            child = self.gpu_container.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.gpu_container.remove(child)
                child = nxt
            self.gpu_panels = []
            for _ in snap.gpus:
                p = GpuPanel()
                self.gpu_container.append(p)
                self.gpu_panels.append(p)
        for panel, gpu in zip(self.gpu_panels, snap.gpus):
            panel.update(gpu)
        if not snap.gpus and not self.gpu_panels:
            placeholder = GpuPanel()
            placeholder.update(None)
            self.gpu_container.append(placeholder)
            self.gpu_panels.append(placeholder)

        # network pill — auto-scale Mbps → KB/s | MB/s | GB/s for readability
        d_val, d_unit = _fmt_speed(snap.net.get("down_mbps", 0))
        u_val, u_unit = _fmt_speed(snap.net.get("up_mbps", 0))
        self.net_down.set_label(d_val); self.net_down_unit.set_label(d_unit)
        self.net_up.set_label(u_val);   self.net_up_unit.set_label(u_unit)

        # weather pill
        if snap.weather:
            self.weather_symbol.set_label(snap.weather["symbol"])
            self.weather_temp.set_label(f"{snap.weather['temp_c']:.1f}")

        # match pill
        self._update_match(snap.next_match)

        # status: live
        self.sensor_status.set_label("LIVE")

    def populate_deck(self, apps: list[dict], macros: list[dict], *,
                      hold_to_confirm: bool, isolate: bool = True,
                      app_slots: int = 9) -> None:
        self.deck.populate(apps, macros, hold_to_confirm=hold_to_confirm,
                           isolate=isolate, app_slots=app_slots)

    # ----- match widget rendering -----

    def _update_match(self, match: dict | None) -> None:
        if not match:
            self.match_opponent.set_label("--")
            self.match_when.set_label("no fixture")
            return

        opponent = match.get("opponent") or "?"
        is_home = bool(match.get("is_home"))
        prefix = "vs" if is_home else "@"
        self.match_opponent.set_label(f"{prefix} {opponent}")

        try:
            kickoff = datetime.fromisoformat(match["kickoff_utc"])
        except (KeyError, ValueError):
            self.match_when.set_label(match.get("competition") or "")
            return

        now = datetime.now(timezone.utc)
        local = kickoff.astimezone()
        comp = match.get("competition") or "Match"

        if match.get("is_past"):
            score = match.get("score") or "—"
            self.match_when.set_label(f"FT {score} · {comp}")
            self.match_box.set_tooltip_text(
                f"Last match: {opponent} ({comp}) — {local.strftime('%a %d %b %H:%M')}"
            )
            return

        delta = kickoff - now
        days = delta.days
        if days < 0:
            label = "live"
        elif days == 0 and now.date() == local.date():
            label = f"today {local.strftime('%H:%M')}"
        elif days <= 1:
            label = f"tomorrow {local.strftime('%H:%M')}"
        elif days < 7:
            label = local.strftime("%a %H:%M")
        else:
            label = local.strftime("%d %b %H:%M")

        self.match_when.set_label(f"{label} · {comp}")
        self.match_box.set_tooltip_text(
            f"Next match: {('home' if is_home else 'away')} vs {opponent} ({comp})\n"
            f"{local.strftime('%a %d %b %Y, %H:%M %Z')}"
        )

    def set_chart_url(self, url: str) -> None:
        """Chart-Panel auf eine neue URL umhaengen (Settings -> General).

        Neu bauen statt ``load_uri``: der Widget-Modus laedt HTML aus einem
        String, der Account-Modus braucht eine persistente ``NetworkSession``
        — das ist nicht dieselbe WebView, also wird sie ersetzt. Unveraenderte
        URL bleibt unangetastet, sonst wuerde jedes Anwenden im
        Settings-Dialog den Chart neu laden.
        """
        url = (url or "").strip()
        if url == self._chart_url:
            return
        self._chart_url = url
        old = self.chart_holder.get_first_child()
        if old is not None:
            self.chart_holder.remove(old)
        self.chart_holder.append(make_chart_widget(url))
