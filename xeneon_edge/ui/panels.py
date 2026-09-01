"""Sensor panels: CPU, GPU, RAM, Top Processes."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

from .gauges import BarGauge
from ..sensors.processes import kill_pid

# Every label that shows a changing number gets a fixed character reserve, so a
# value going from "9%" to "100%" (or 1 GB to 12 GB) can't widen its row.
# "tnum" in the CSS makes digits equal-width, so the reserve is exact.
VALUE_CHARS = 14   # metric rows: "125.6 / 128.0 GB"
CPU_CHARS = 5      # "100%"
RAM_CHARS = 8      # "12345 MB"
RPM_CHARS = 9      # "12345 RPM"


def _pin_width(label: Gtk.Label, chars: int) -> Gtk.Label:
    """Reserve exactly ``chars`` — minimum and natural width become identical."""
    label.set_width_chars(chars)
    label.set_max_width_chars(chars)
    label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
    return label


def _panel(title: str, sub: str = "") -> tuple[Gtk.Box, Gtk.Label, Gtk.Box]:
    """Creates a base panel box with header. Returns (panel_box, sublabel, body_box)."""
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    panel.add_css_class("panel")
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    header.add_css_class("panel-header")
    title_lbl = Gtk.Label(label=title, xalign=0)
    title_lbl.add_css_class("panel-label")
    sub_lbl = Gtk.Label(label=sub, xalign=1)
    sub_lbl.add_css_class("panel-sublabel")
    sub_lbl.set_hexpand(True)
    sub_lbl.set_ellipsize(3)  # ELLIPSIZE_END — long GPU/RAM names won't push out
    header.append(title_lbl)
    header.append(sub_lbl)
    panel.append(header)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    panel.append(body)
    return panel, sub_lbl, body


def _metric_row(name: str) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label, BarGauge]:
    row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    name_lbl = Gtk.Label(label=name, xalign=0)
    name_lbl.add_css_class("metric-name")
    name_lbl.set_hexpand(True)
    val_lbl = Gtk.Label(label="--", xalign=1)
    val_lbl.add_css_class("metric-value")
    _pin_width(val_lbl, VALUE_CHARS)
    line.append(name_lbl)
    line.append(val_lbl)
    gauge = BarGauge()
    row.append(line)
    row.append(gauge)
    return row, name_lbl, val_lbl, gauge


class CpuPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.sub, body = _panel("CPU", "")
        self.append(self.panel)

        load_row, _, self.load_val, self.load_gauge = _metric_row("LOAD")
        temp_row, _, self.temp_val, self.temp_gauge = _metric_row("TEMP")
        clk_row, _, self.clk_val, _self_clk_gauge = _metric_row("CLOCK")
        # for clock, hide gauge — replace with empty
        body.append(load_row)
        body.append(temp_row)
        body.append(clk_row)

    def update(self, cpu: dict, name: str = "CPU") -> None:
        self.sub.set_label(name)
        load = cpu.get("load_pct")
        temp = cpu.get("temp_c")
        clk = cpu.get("clock_mhz")
        self.load_val.set_label(f"{load:.0f}%" if load is not None else "--")
        self.load_gauge.set_value(load)
        self.temp_val.set_label(f"{temp:.0f}°C" if temp is not None else "--")
        # map 30-90°C → 0-100% for gauge color thresholds
        self.temp_gauge.set_value(((temp - 30) / 60 * 100) if temp is not None else 0)
        self.clk_val.set_label(f"{clk/1000:.2f} GHz" if clk is not None else "--")


class GpuPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.sub, body = _panel("GPU", "")
        self.append(self.panel)

        load_row, _, self.load_val, self.load_gauge = _metric_row("LOAD")
        temp_row, _, self.temp_val, self.temp_gauge = _metric_row("TEMP")
        vram_row, _, self.vram_val, self.vram_gauge = _metric_row("VRAM")
        clk_row, _, self.clk_val, _ = _metric_row("CORE")
        body.append(load_row)
        body.append(temp_row)
        body.append(vram_row)
        body.append(clk_row)

    def update(self, gpu: dict | None) -> None:
        if gpu is None:
            self.sub.set_label("offline")
            for lbl in (self.load_val, self.temp_val, self.vram_val, self.clk_val):
                lbl.set_label("--")
            self.load_gauge.set_value(0); self.temp_gauge.set_value(0); self.vram_gauge.set_value(0)
            return
        self.sub.set_label(gpu.get("name") or "GPU")
        load = gpu.get("load_pct")
        temp = gpu.get("temp_c")
        vu = gpu.get("vram_used_gb")
        vt = gpu.get("vram_total_gb")
        clk = gpu.get("core_mhz")
        self.load_val.set_label(f"{load:.0f}%" if load is not None else "--")
        self.load_gauge.set_value(load)
        self.temp_val.set_label(f"{temp:.0f}°C" if temp is not None else "--")
        self.temp_gauge.set_value(((temp - 30) / 60 * 100) if temp is not None else 0)
        if vu is not None and vt:
            self.vram_val.set_label(f"{vu:.1f} / {vt:.1f} GB")
            self.vram_gauge.set_value(vu / vt * 100)
        else:
            self.vram_val.set_label("--"); self.vram_gauge.set_value(0)
        # AMD sclk idles to 0 MHz in deep power states; 0 is a real reading,
        # so test for None (not falsiness) to avoid flickering to "--".
        self.clk_val.set_label(f"{clk:.0f} MHz" if clk is not None else "--")


class RamPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.sub, body = _panel("RAM", "-- GB")
        self.append(self.panel)
        load_row, _, self.load_val, self.load_gauge = _metric_row("USED")
        body.append(load_row)

    def update(self, ram: dict) -> None:
        used = ram.get("used_gb")
        total = ram.get("total_gb")
        load = ram.get("load_pct")
        if total:
            self.sub.set_label(f"{total:.0f} GB DDR5")
        if used is not None and total:
            self.load_val.set_label(f"{used:.1f} / {total:.1f} GB")
        else:
            self.load_val.set_label("--")
        self.load_gauge.set_value(load)


class ProcessRow(Gtk.Box):
    """One process line: name · CPU% · RAM · hold-to-kill button."""

    __gtype_name__ = "XeProcessRow"

    # GestureLongPress fires after gtk-long-press-time (500 ms) × delay_factor.
    HOLD_FACTOR = 1.6  # ≈ 800 ms

    def __init__(self, *, on_kill):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("proc-row")
        self._on_kill = on_kill
        self._pid: int | None = None
        self._name = ""
        self._arming = False

        self.name_lbl = Gtk.Label(label="—", xalign=0)
        self.name_lbl.add_css_class("proc-name")
        self.name_lbl.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        self.name_lbl.set_hexpand(True)
        self.cpu_lbl = _pin_width(Gtk.Label(label="", xalign=1), CPU_CHARS)
        self.cpu_lbl.add_css_class("proc-cpu")
        self.ram_lbl = _pin_width(Gtk.Label(label="", xalign=1), RAM_CHARS)
        self.ram_lbl.add_css_class("proc-ram")

        self.kill_btn = Gtk.Button(label="×")
        self.kill_btn.add_css_class("proc-kill")
        self.kill_btn.set_valign(Gtk.Align.CENTER)
        self.kill_btn.set_sensitive(False)
        # A plain click does nothing — the button has to be *held*, same
        # safeguard the dangerous deck macros use.
        self.kill_btn.connect("clicked", lambda *_: None)
        gesture = Gtk.GestureLongPress.new()
        gesture.set_delay_factor(self.HOLD_FACTOR)
        gesture.connect("pressed", self._on_long_pressed)
        self.kill_btn.add_controller(gesture)
        # The :active state flag is the reliable press/release signal here —
        # a second click gesture would fight the button's own one.
        self.kill_btn.connect("state-flags-changed", self._on_state_flags)

        for w in (self.name_lbl, self.cpu_lbl, self.ram_lbl, self.kill_btn):
            self.append(w)

    # ---- content

    def set_process(self, p: dict | None) -> None:
        if p is None:
            self._pid = None
            self._name = ""
            self.name_lbl.set_label("—")
            self.cpu_lbl.set_label("")
            self.ram_lbl.set_label("")
            self.kill_btn.set_sensitive(False)
            self.kill_btn.set_tooltip_text(None)
            return
        self._pid = p["pid"]
        self._name = p["name"]
        self.name_lbl.set_label(self._name)
        self.cpu_lbl.set_label(f"{p['cpu_pct']:.0f}%")
        self.ram_lbl.set_label(f"{p['ram_mb']:.0f} MB")
        self.kill_btn.set_sensitive(True)
        self.kill_btn.set_tooltip_text(
            f"× gedrückt halten (~0.8 s) → {self._name} beenden (PID {self._pid})"
        )

    def is_arming(self) -> bool:
        return self._arming

    # ---- hold-to-confirm

    def _on_state_flags(self, btn: Gtk.Button, _old) -> None:
        active = bool(btn.get_state_flags() & Gtk.StateFlags.ACTIVE)
        if active == self._arming:
            return
        self._arming = active
        # .arming fades to red over the hold duration (see style.css); dropping
        # the class snaps back fast, so an aborted hold reads as "cancelled".
        if active:
            btn.add_css_class("arming")
        else:
            btn.remove_css_class("arming")

    def _on_long_pressed(self, _gesture, _x, _y) -> None:
        if self._pid is None:
            return
        ok = self._on_kill(self._pid, self._name)
        self.kill_btn.remove_css_class("arming")
        self.kill_btn.add_css_class("killed" if ok else "fail")
        GLib.timeout_add(700, self._clear_flash)

    def _clear_flash(self) -> bool:
        self.kill_btn.remove_css_class("killed")
        self.kill_btn.remove_css_class("fail")
        return False


class ProcessPanel(Gtk.Box):
    # Matches the aggregator's top_processes(14) — a fixed pool means the panel
    # height is a constant too, not just its width.
    ROWS = 14

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.sub, self.body = _panel("Top Processes", "CPU · RAM")
        self.append(self.panel)
        # Fixed pool of rows, built once. Rebuilding them every tick would reset
        # an in-progress hold and make the panel height jump when the process
        # count changes.
        self._rows = [ProcessRow(on_kill=self._kill) for _ in range(self.ROWS)]
        for r in self._rows:
            self.body.append(r)

    def update(self, procs: list[dict]) -> None:
        # Freeze while a × is held down — otherwise a reorder mid-hold would
        # swap the target out from under the user and kill the wrong process.
        if any(r.is_arming() for r in self._rows):
            return
        for i, row in enumerate(self._rows):
            row.set_process(procs[i] if i < len(procs) else None)

    def _kill(self, pid: int, name: str) -> bool:
        ok = kill_pid(pid)
        print(f"[xeneon-edge] {'terminated' if ok else 'could not terminate'} {name} (PID {pid})")
        return ok


class FanPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.sub, self.body = _panel("Fans", "RPM")
        self.append(self.panel)
        self._rows: list[Gtk.Box] = []

    def update(self, fans: list[dict]) -> None:
        for r in self._rows:
            self.body.remove(r)
        self._rows.clear()
        # Hide the whole panel when no fan sensors were detected — frees up
        # vertical space for CPU/GPU/RAM in the sensor column.
        if not fans:
            self.set_visible(False)
            return
        self.set_visible(True)
        for f in fans:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("proc-row")
            name = Gtk.Label(label=f["label"], xalign=0); name.add_css_class("proc-name")
            name.set_ellipsize(3); name.set_hexpand(True)
            rpm = _pin_width(Gtk.Label(label=f"{f['rpm']} RPM", xalign=1), RPM_CHARS)
            rpm.add_css_class("proc-ram")
            row.append(name); row.append(rpm)
            self.body.append(row)
            self._rows.append(row)
