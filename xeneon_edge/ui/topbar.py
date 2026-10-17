"""Topbar-Widgets: Marke, Statuspille, Netz, Wetter, Uhr, Spiel.

Bis Schritt 4 standen sie fest in window.py. Jetzt sind sie Widgets wie die
Spalten-Module: ``update(snapshot)`` bei jedem Sensor-Tick, ``tick()`` einmal
pro Sekunde vom Fenster (Uhr, Datenalter), ``feeds`` sagt dem Aggregator,
was er dafuer aus dem Netz holen muss.
"""
from __future__ import annotations
from datetime import datetime, timezone
import time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

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


def _pill() -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.add_css_class("pill")
    return box


def _float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class BrandWidget(Gtk.Box):
    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        # Drei Labels statt Pango-Markup: der Akzent des "//" kommt so aus dem
        # Theme (label.brand-accent) und nicht aus einem festen Hex-Wert.
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        for text, css in (("XENEON", "brand"), ("//", "brand-accent"), ("EDGE", "brand")):
            part = Gtk.Label(label=text, xalign=0)
            part.add_css_class(css)
            line.append(part)
        sub = Gtk.Label(label=str(config.get("subtitle") or "COMMAND CENTER"), xalign=0)
        sub.add_css_class("brand-sub")
        self.append(line)
        self.append(sub)


class StatusPill(Gtk.Box):
    """Welche Quelle liest, und ob die Daten frisch sind.

    Stand frueher konstant auf "LIVE" — auch bei stehengebliebenem
    Sensor-Thread. Ein eingefrorenes Dashboard sieht aber aus wie ein ruhiges
    System, und genau das soll hier auffallen. ``tick()`` prueft das Alter
    auch dann, wenn gar keine Snapshots mehr kommen.
    """

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("pill")
        self.label = _pin(Gtk.Label(label="Sensors warming up", xalign=0), 21)
        self.label.add_css_class("pill-text")
        self.append(self.label)
        self._last_at = 0.0
        self._sources: dict = {}

    def update(self, snap) -> None:
        self._last_at = getattr(snap, "taken_at", 0.0) or time.time()
        self._sources = getattr(snap, "sources", {}) or {}
        self.tick()

    def tick(self) -> None:
        if not self._last_at:
            self.label.set_label("Sensors warming up")
            self.label.remove_css_class("status-stale")
            return
        age = time.time() - self._last_at
        if age > STALE_AFTER_S:
            self.label.set_label(f"STALE {age:.0f}s")
            self.label.add_css_class("status-stale")
            return
        self.label.remove_css_class("status-stale")
        gpu = self._sources.get("gpu")
        self.label.set_label(f"LIVE · {gpu}" if gpu else "LIVE")


class NetPill(Gtk.Box):
    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("pill")
        # Fixed char reserves — "1.2" → "123.4" and "KB/s" → "MB/s" must not
        # resize the pill (and with it the whole topbar) as traffic changes.
        d_arrow = Gtk.Label(label="↓"); d_arrow.add_css_class("arrow")
        self.down = _pin(Gtk.Label(label="--", xalign=1), 5); self.down.add_css_class("pill-strong")
        self.down_unit = _pin(Gtk.Label(label="KB/s", xalign=0), 7); self.down_unit.add_css_class("pill-text")
        u_arrow = Gtk.Label(label="↑"); u_arrow.add_css_class("arrow")
        self.up = _pin(Gtk.Label(label="--", xalign=1), 5); self.up.add_css_class("pill-strong")
        self.up_unit = _pin(Gtk.Label(label="KB/s", xalign=0), 7); self.up_unit.add_css_class("pill-text")
        for w in (d_arrow, self.down, self.down_unit, u_arrow, self.up, self.up_unit):
            self.append(w)

    def update(self, snap) -> None:
        d_val, d_unit = _fmt_speed(snap.net.get("down_mbps", 0))
        u_val, u_unit = _fmt_speed(snap.net.get("up_mbps", 0))
        self.down.set_label(d_val); self.down_unit.set_label(d_unit)
        self.up.set_label(u_val); self.up_unit.set_label(u_unit)


class WeatherPill(Gtk.Box):
    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("panel"); self.add_css_class("topbar-pill")
        lat, lon = _float(config.get("lat")), _float(config.get("lon"))
        self.feeds = {"weather": {"lat": lat, "lon": lon}} if lat is not None and lon is not None else {}
        self.symbol = Gtk.Label(label="--"); self.symbol.add_css_class("weather-symbol")
        self.temp = _pin(Gtk.Label(label="--", xalign=1), 5)
        self.temp.add_css_class("weather-temp-strong")
        unit = Gtk.Label(label="°C"); unit.add_css_class("weather-temp")
        self.append(self.symbol); self.append(self.temp); self.append(unit)
        label = str(config.get("label") or "")
        if not self.feeds:
            # Ohne Standort gibt es nichts zu holen — das sagt die Pille
            # selbst, statt fuer immer "--" zu zeigen.
            self.set_tooltip_text("No location set — enter lat/lon in the editor")
            self.symbol.set_label("?")
        elif label:
            self.set_tooltip_text(label)

    def update(self, snap) -> None:
        if snap.weather:
            self.symbol.set_label(snap.weather["symbol"])
            self.temp.set_label(f"{snap.weather['temp_c']:.1f}")


class ClockWidget(Gtk.Box):
    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.set_halign(Gtk.Align.CENTER)
        self._seconds = bool(config.get("seconds"))
        self.time = Gtk.Label(label="00:00", xalign=0.5); self.time.add_css_class("clock-time")
        self.date = _pin(Gtk.Label(label="--", xalign=0.5), 15)
        self.date.add_css_class("clock-date")
        self.append(self.time); self.append(self.date)
        self.tick()

    def tick(self) -> None:
        now = datetime.now()
        self.time.set_label(now.strftime("%H:%M:%S" if self._seconds else "%H:%M"))
        self.date.set_label(now.strftime("%A").upper())


class MatchPill(Gtk.Box):
    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.add_css_class("panel"); self.add_css_class("topbar-pill"); self.add_css_class("match-widget")
        league = str(config.get("league") or "").strip()
        team = str(config.get("team") or "").strip()
        self.feeds = {"match": {"league": league, "team": team}} if league and team else {}
        badge = Gtk.Label(label=str(config.get("short") or "⚽")); badge.add_css_class("match-team")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.opponent = _pin(Gtk.Label(label="--", xalign=0), 19); self.opponent.add_css_class("match-opponent")
        self.when = _pin(Gtk.Label(label="--", xalign=0), 22); self.when.add_css_class("match-when")
        text.append(self.opponent); text.append(self.when)
        self.append(badge); self.append(text)
        if not self.feeds:
            self.when.set_label("no team set")
            self.set_tooltip_text("Enter league and team ID in the editor (ESPN)")

    def update(self, snap) -> None:
        if not self.feeds:
            return
        match = snap.next_match
        if not match:
            self.opponent.set_label("--")
            self.when.set_label("no fixture")
            return

        opponent = match.get("opponent") or "?"
        is_home = bool(match.get("is_home"))
        self.opponent.set_label(f"{'vs' if is_home else '@'} {opponent}")

        try:
            kickoff = datetime.fromisoformat(match["kickoff_utc"])
        except (KeyError, ValueError):
            self.when.set_label(match.get("competition") or "")
            return

        now = datetime.now(timezone.utc)
        local = kickoff.astimezone()
        comp = match.get("competition") or "Match"

        if match.get("is_past"):
            score = match.get("score") or "—"
            self.when.set_label(f"FT {score} · {comp}")
            self.set_tooltip_text(
                f"Last match: {opponent} ({comp}) — {local.strftime('%a %d %b %H:%M')}")
            return

        # Kalendertage in Ortszeit vergleichen, nicht timedelta.days: der
        # zaehlt volle 24-h-Spannen, und now.date() waere ein UTC-Datum —
        # nach Mitternacht Ortszeit hiess ein Spiel am selben Tag "tomorrow".
        days = (local.date() - now.astimezone().date()).days
        if kickoff <= now:
            label = "live"
        elif days == 0:
            label = f"today {local.strftime('%H:%M')}"
        elif days == 1:
            label = f"tomorrow {local.strftime('%H:%M')}"
        elif days < 7:
            label = local.strftime("%a %H:%M")
        else:
            label = local.strftime("%d %b %H:%M")
        self.when.set_label(f"{label} · {comp}")
        self.set_tooltip_text(
            f"Next match: {('home' if is_home else 'away')} vs {opponent} ({comp})\n"
            f"{local.strftime('%a %d %b %Y, %H:%M %Z')}")


class ActionsWidget(Gtk.Box):
    """Zahnrad, Vollbild, Schliessen — immer ganz rechts, nicht im Layout.

    Absichtlich nicht abwaehlbar: ohne Zahnrad kaeme man am Streifen nicht
    mehr in den Editor, der es wieder einschalten koennte.
    """

    def __init__(self, *, on_open_settings, on_toggle_fullscreen, on_close):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_btn = Gtk.Button(label="⚙"); settings_btn.add_css_class("ico")
        settings_btn.set_tooltip_text("Open the editor on the main monitor")
        settings_btn.connect("clicked", lambda *_: on_open_settings())
        fs_btn = Gtk.Button(label="FS"); fs_btn.add_css_class("ico")
        fs_btn.connect("clicked", lambda *_: on_toggle_fullscreen())
        close_btn = Gtk.Button(label="X"); close_btn.add_css_class("ico"); close_btn.add_css_class("danger")
        close_btn.connect("clicked", lambda *_: on_close())
        for b in (settings_btn, fs_btn, close_btn):
            self.append(b)
