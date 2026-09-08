"""Main window: topbar + 3-column grid (sensor stack, chart, right stack) + deck."""
from __future__ import annotations
from datetime import datetime, timezone
import time
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib  # noqa: E402

from .layout import FixedWidth
from .. import config_store, layout_store, modules

# Spaltenbreiten stehen in layout.json, nicht mehr hier. FixedWidth meldet sie
# als Minimum *und* Natural, damit kein Wert im Inneren die Spalte verschieben
# kann; genau eine Spalte ist "flex" und nimmt den Rest.
#
# Alter der Sensordaten, ab dem die Statuspille nicht mehr LIVE zeigt. Der
# Aggregator tickt mit 1 Hz, drei verpasste Ticks sind also kein Jitter mehr,
# sondern ein haengender oder toter Sensor-Thread.
STALE_AFTER_S = 3.0


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
    def __init__(self, app: Adw.Application, *, on_open_settings, palette=None):
        super().__init__(application=app)
        # Aktive Palette — Web-Module bekommen sie beim Bau, damit das
        # TradingView-Widget in denselben Farben startet wie der Rest.
        self._palette = palette
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
        # Drei Labels statt Pango-Markup: der Akzent des "//" kommt so aus dem
        # Theme (label.brand-accent) und nicht aus einem festen Hex-Wert.
        brand_label = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        for text, css in (("XENEON", "brand"), ("//", "brand-accent"), ("EDGE", "brand")):
            part = Gtk.Label(label=text, xalign=0)
            part.add_css_class(css)
            brand_label.append(part)
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

        # ----- Hauptgitter: eine Zeile, Spalten laut layout.json -----
        # Der Halter bleibt im Fenster stehen; apply_layout() tauscht nur sein
        # Kind, damit ein Layout-Wechsel den Rest des Fensters nicht anfasst.
        self.grid_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.grid_holder.set_hexpand(True)
        self.grid_holder.set_vexpand(True)
        outer.append(self.grid_holder)

        # Gebaute Module in Layout-Reihenfolge. apply_snapshot() geht diese
        # Liste durch, statt feste Attribute anzusprechen — nach einem Rebuild
        # zeigt sie auf die neuen Widgets, die alten sind weg.
        self._modules: list[Gtk.Widget] = []
        self._last_snapshot_at: float = 0.0
        self._sensor_sources: dict[str, str] = {}

        self.apply_layout(layout_store.load())

        # tick the clock every second
        self._update_clock()
        GLib.timeout_add_seconds(1, self._update_clock)
        # Statuspille prueft das Alter der Daten auch dann, wenn gar keine mehr
        # kommen — ein Snapshot-Handler allein wuerde bei totem Sensor-Thread
        # nie wieder feuern und die Pille bliebe fuer immer auf LIVE stehen.
        GLib.timeout_add_seconds(1, self._refresh_status_pill)

    # ----- layout -----

    def apply_layout(self, layout: dict) -> None:
        """Gitter aus einem Layout neu bauen.

        Laeuft auf dem GTK-Main-Loop, und apply_snapshot() greift nur ueber
        self._modules zu — ein Rebuild kann also keine Aktualisierung auf einem
        bereits abgeraeumten Widget hinterlassen.
        """
        profile = layout_store.active_profile(layout)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.set_column_homogeneous(False)

        built: list[Gtk.Widget] = []
        for index, column in enumerate(profile["columns"]):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_vexpand(True)

            for entry in column["modules"]:
                config = dict(entry.get("config") or {})
                config["_palette"] = self._palette
                widget = modules.build(entry["type"], config)
                if widget is None:
                    continue
                widget.set_vexpand(True)
                box.append(widget)
                built.append(widget)

            if column["width"] == layout_store.FLEX:
                box.set_hexpand(True)
                grid.attach(box, index, 0, 1, 1)
            else:
                # Nicht um Breite mit der Flex-Spalte konkurrieren.
                box.set_hexpand(False)
                grid.attach(FixedWidth(box, column["width"]), index, 0, 1, 1)

        old = self.grid_holder.get_first_child()
        if old is not None:
            self.grid_holder.remove(old)
        self.grid_holder.append(grid)
        self._modules = built
        self._layout = layout

    def find_module(self, type_id: str) -> Gtk.Widget | None:
        """Erstes gebautes Modul eines Typs — fuer app.py, das das Deck befuellt."""
        spec = modules.get(type_id)
        if spec is None:
            return None
        for widget in self._modules:
            if isinstance(widget, spec.factory):
                return widget
        return None

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
        # Ueber die Liste, nicht ueber feste Attribute: nach apply_layout()
        # zeigt sie auf die aktuellen Module. Ein Modul, das sich verschluckt,
        # darf die uebrigen nicht mitreissen.
        for widget in self._modules:
            update = getattr(widget, "update", None)
            if update is None:
                continue
            try:
                update(snap)
            except Exception as e:
                print(f"[xeneon-edge] Modul {type(widget).__name__} update: {e}")

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

        self._last_snapshot_at = getattr(snap, "taken_at", 0.0) or time.time()
        self._sensor_sources = getattr(snap, "sources", {}) or {}
        self._refresh_status_pill()

    def populate_deck(self, apps: list[dict], macros: list[dict], *,
                      hold_to_confirm: bool, isolate: bool = True,
                      app_slots: int = 9) -> None:
        deck = self.find_module("deck")
        if deck is None:
            return
        deck.populate(apps, macros, hold_to_confirm=hold_to_confirm,
                      isolate=isolate, app_slots=app_slots)

    # ----- status pill -----

    def _refresh_status_pill(self) -> bool:
        """Was die Pille zeigt: welche Quelle liest, und ob die Daten frisch sind.

        Sie stand frueher konstant auf "LIVE" und war damit reine Dekoration —
        auch bei stehengebliebenem Sensor-Thread. Ein eingefrorenes Dashboard
        sieht aber aus wie ein ruhiges System, und genau das soll hier
        auffallen.
        """
        if not self._last_snapshot_at:
            self.sensor_status.set_label("Sensors warming up")
            self.sensor_status.remove_css_class("status-stale")
            return True

        age = time.time() - self._last_snapshot_at
        if age > STALE_AFTER_S:
            self.sensor_status.set_label(f"STALE {age:.0f}s")
            self.sensor_status.add_css_class("status-stale")
            return True

        self.sensor_status.remove_css_class("status-stale")
        gpu = self._sensor_sources.get("gpu")
        self.sensor_status.set_label(f"LIVE · {gpu}" if gpu else "LIVE")
        return True

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

    def apply_palette(self, palette) -> None:
        """Theme-Wechsel zur Laufzeit: Module, die Farben selbst rendern, informieren."""
        self._palette = palette
        for widget in self._modules:
            hook = getattr(widget, "set_palette", None)
            if hook is not None:
                try:
                    hook(palette)
                except Exception as e:
                    print(f"[xeneon-edge] Modul {type(widget).__name__} set_palette: {e}")

    def set_chart_url(self, url: str) -> None:
        """URL des ersten Web-Moduls wechseln (Settings -> General).

        Neu bauen statt ``load_uri``: der Widget-Modus laedt HTML aus einem
        String, der Account-Modus braucht eine persistente ``NetworkSession``
        — das ist nicht dieselbe WebView, also wird sie ersetzt. Unveraenderte
        URL bleibt unangetastet, sonst wuerde jedes Anwenden im
        Settings-Dialog den Chart neu laden.
        """
        web = self.find_module("web")
        if web is not None:
            web.set_url((url or "").strip())
