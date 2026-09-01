"""Audio panel: sliders + dropdowns for output/input device + volume + mute."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject  # noqa: E402

from ..sensors import audio as audio_mod


def _make_factory(*, narrow: bool) -> Gtk.SignalListItemFactory:
    """Factory that renders Gtk.StringObject items as labels.

    narrow=True  → for the trigger button: ellipsize, claim minimal width
                   so a long device name can't push the column wide.
    narrow=False → for the popup list: full text, no width clamp."""
    factory = Gtk.SignalListItemFactory()

    def setup(_f, item):
        label = Gtk.Label(xalign=0)
        if narrow:
            label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            label.set_max_width_chars(1)
            label.set_width_chars(1)
        else:
            label.set_xalign(0)
            label.set_margin_top(2)
            label.set_margin_bottom(2)
            label.set_margin_start(6)
            label.set_margin_end(6)
        item.set_child(label)

    def bind(_f, item):
        label = item.get_child()
        obj = item.get_item()
        label.set_label(obj.get_string() if obj else "")

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


def _pin_pct(label: Gtk.Label) -> Gtk.Label:
    """Fixed reserve for the volume readout — "5%" and "100%" must be equal wide."""
    label.set_width_chars(5)
    label.set_max_width_chars(5)
    label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
    return label


def _flip_popover_up(dropdown: Gtk.DropDown) -> None:
    """Walk the DropDown's children to find its internal Gtk.Popover and
    set its position to TOP (i.e. open upward — 'dropup')."""
    def walk(w: Gtk.Widget) -> Gtk.Popover | None:
        child = w.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Popover):
                return child
            found = walk(child)
            if found is not None:
                return found
            child = child.get_next_sibling()
        return None

    popover = walk(dropdown)
    if popover is not None:
        popover.set_position(Gtk.PositionType.TOP)


class AudioPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("panel")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Audio", xalign=0); title.add_css_class("panel-label")
        self.status = Gtk.Label(label="--", xalign=1); self.status.add_css_class("panel-sublabel")
        self.status.set_hexpand(True)
        head.append(title); head.append(self.status)
        self.append(head)

        # Output row
        out_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.out_mute_btn = Gtk.Button(label="♫")
        self.out_mute_btn.add_css_class("ico")
        self.out_mute_btn.connect("clicked", self._on_out_mute)
        self.out_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.out_scale.set_hexpand(True)
        self.out_scale.set_draw_value(False)
        self._out_scale_handler = self.out_scale.connect("value-changed", self._on_out_scale)
        self.out_val = _pin_pct(Gtk.Label(label="--", xalign=1))
        self.out_val.add_css_class("metric-value-accent")
        out_row.append(self.out_mute_btn); out_row.append(self.out_scale); out_row.append(self.out_val)
        self.append(out_row)

        # Output device dropdown
        self.out_dropdown = Gtk.DropDown.new_from_strings([])
        self.out_dropdown.set_factory(_make_factory(narrow=True))
        self.out_dropdown.set_list_factory(_make_factory(narrow=False))
        self.out_dropdown.set_hexpand(False)
        self.out_dropdown.set_size_request(40, -1)  # don't claim natural width
        self._out_dropdown_handler = self.out_dropdown.connect("notify::selected", self._on_out_select)
        self.append(self.out_dropdown)
        _flip_popover_up(self.out_dropdown)

        # Input row
        in_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.in_mute_btn = Gtk.Button(label="🎤")
        self.in_mute_btn.add_css_class("ico")
        self.in_mute_btn.connect("clicked", self._on_in_mute)
        self.in_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.in_scale.set_hexpand(True)
        self.in_scale.set_draw_value(False)
        self._in_scale_handler = self.in_scale.connect("value-changed", self._on_in_scale)
        self.in_val = _pin_pct(Gtk.Label(label="--", xalign=1))
        self.in_val.add_css_class("metric-value-accent")
        in_row.append(self.in_mute_btn); in_row.append(self.in_scale); in_row.append(self.in_val)
        self.append(in_row)

        self.in_dropdown = Gtk.DropDown.new_from_strings([])
        self.in_dropdown.set_factory(_make_factory(narrow=True))
        self.in_dropdown.set_list_factory(_make_factory(narrow=False))
        self.in_dropdown.set_hexpand(False)
        self.in_dropdown.set_size_request(40, -1)
        self._in_dropdown_handler = self.in_dropdown.connect("notify::selected", self._on_in_select)
        self.append(self.in_dropdown)
        _flip_popover_up(self.in_dropdown)

        self._state: dict | None = None
        self._suppress = False  # avoid feedback when we update from snapshot

    # ---- snapshot → UI

    def update(self, state: dict | None) -> None:
        if not state:
            self.status.set_label("not available")
            return
        self._suppress = True
        try:
            outs = state.get("outputs") or []
            ins = state.get("inputs") or []
            active_out = state.get("active_output_id")
            active_in = state.get("active_input_id")

            self._set_dropdown(self.out_dropdown, self._out_dropdown_handler, outs, active_out)
            self._set_dropdown(self.in_dropdown, self._in_dropdown_handler, ins, active_in)

            ov = int(state.get("output_volume") or 0)
            iv = int(state.get("input_volume") or 0)
            ov_m = bool(state.get("output_muted"))
            iv_m = bool(state.get("input_muted"))

            with GObject.signal_handler_block(self.out_scale, self._out_scale_handler):
                self.out_scale.set_value(ov)
            with GObject.signal_handler_block(self.in_scale, self._in_scale_handler):
                self.in_scale.set_value(iv)

            self.out_val.set_label(f"{'M' if ov_m else ov}{'%' if not ov_m else ''}")
            self.in_val.set_label(f"{'M' if iv_m else iv}{'%' if not iv_m else ''}")
            self.status.set_label("muted" if ov_m else f"{ov}%")
        finally:
            self._state = state
            self._suppress = False

    def _set_dropdown(self, dropdown: Gtk.DropDown, handler_id: int,
                      items: list[dict], active_id: str | None) -> None:
        labels = [it.get("name") or it.get("id") or "?" for it in items]
        cur_model = dropdown.get_model()
        # Rebuild only when label set differs
        if cur_model is not None:
            cur = [cur_model.get_string(i) for i in range(cur_model.get_n_items())]
            if cur == labels:
                # update selection only
                if active_id is not None:
                    idx = next((i for i, it in enumerate(items) if it["id"] == active_id), -1)
                    if idx >= 0 and dropdown.get_selected() != idx:
                        with GObject.signal_handler_block(dropdown, handler_id):
                            dropdown.set_selected(idx)
                return
        new_model = Gtk.StringList.new(labels)
        with GObject.signal_handler_block(dropdown, handler_id):
            dropdown.set_model(new_model)
            if active_id is not None:
                idx = next((i for i, it in enumerate(items) if it["id"] == active_id), 0)
                dropdown.set_selected(idx)
        # cache for selection lookups in callbacks
        dropdown._xe_items = items  # type: ignore[attr-defined]

    # ---- UI → audio backend

    def _on_out_scale(self, scale: Gtk.Scale) -> None:
        if self._suppress or not self._state:
            return
        active = self._state.get("active_output_id")
        if active:
            audio_mod.set_volume("sink", active, int(scale.get_value()))

    def _on_in_scale(self, scale: Gtk.Scale) -> None:
        if self._suppress or not self._state:
            return
        active = self._state.get("active_input_id")
        if active:
            audio_mod.set_volume("source", active, int(scale.get_value()))

    def _on_out_mute(self, _btn) -> None:
        if not self._state:
            return
        active = self._state.get("active_output_id")
        if active:
            audio_mod.set_mute("sink", active, not self._state.get("output_muted"))

    def _on_in_mute(self, _btn) -> None:
        if not self._state:
            return
        active = self._state.get("active_input_id")
        if active:
            audio_mod.set_mute("source", active, not self._state.get("input_muted"))

    def _on_out_select(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._suppress:
            return
        items = getattr(dropdown, "_xe_items", []) or []
        idx = dropdown.get_selected()
        if 0 <= idx < len(items):
            audio_mod.set_default("sink", items[idx]["id"])

    def _on_in_select(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._suppress:
            return
        items = getattr(dropdown, "_xe_items", []) or []
        idx = dropdown.get_selected()
        if 0 <= idx < len(items):
            audio_mod.set_default("source", items[idx]["id"])
