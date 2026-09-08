"""Adw.PreferencesWindow with General / Apps / Macros tabs.

Apps & Macros tabs: changes go into an in-memory working copy first;
they are only persisted when the user clicks Apply.  Cancel reverts to
the on-disk state.  General toggles (autostart, hold-to-confirm) save
immediately because they're idempotent.
"""
from __future__ import annotations
import copy
import os
import shutil
import sys
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib  # noqa: E402

from .. import config_store, theme as theme_mod
from ..paths import ROOT


def _empty_slot(key: str, idx: int) -> dict:
    return {
        "id": f"{key[:-1]}{idx+1}", "label": "", "command": "",
        "args": "", "accent": "#ff0033", "kind": key[:-1],
    }


class SettingsDialog(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, *, on_apply, on_theme=None):
        super().__init__()
        # on_theme(theme_id) — vom Dashboard sofort umgesetzt, kein Apply noetig
        self._on_theme_cb = on_theme
        self.set_modal(True)
        self.set_transient_for(parent)
        self.set_title("Settings")
        self.set_default_size(760, 720)
        self._on_apply_cb = on_apply
        self._settings = config_store.load_settings()
        self._apps_data = config_store.load_apps()
        # working copy — committed only on Apply
        self._working = copy.deepcopy(self._apps_data)
        self._dirty: dict[str, bool] = {"apps": False, "macros": False}
        # gesetzt, sobald der Nachfrage-Dialog beantwortet ist — sonst wuerde
        # self.close() erneut in _on_close laufen und wieder nachfragen
        self._force_close = False

        self._pages: dict[str, Adw.PreferencesPage] = {}
        self._action_groups: dict[str, Adw.PreferencesGroup] = {}
        self._slot_groups: dict[str, Adw.PreferencesGroup] = {}
        self._action_status: dict[str, Gtk.Label] = {}
        self._apply_btns: dict[str, Gtk.Button] = {}
        self._cancel_btns: dict[str, Gtk.Button] = {}

        self._build_general()
        self._build_entries("Apps", "apps")
        self._build_entries("Macros", "macros")

        self.connect("close-request", self._on_close)

    # ----- General tab -----

    def _build_general(self) -> None:
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        group = Adw.PreferencesGroup()
        page.add(group)

        autostart_row = Adw.SwitchRow(
            title="Start with desktop session",
            subtitle="Creates ~/.config/autostart/xeneon-edge.desktop",
        )
        autostart_row.set_active(self._settings.get("auto_start", False))
        autostart_row.connect("notify::active", self._on_autostart)
        group.add(autostart_row)

        hold_row = Adw.SwitchRow(
            title="Hold to confirm dangerous macros",
            subtitle="Long-press required for shutdown/reboot/etc.",
        )
        hold_row.set_active(self._settings.get("hold_to_confirm", True))
        hold_row.connect("notify::active", self._on_hold_to_confirm)
        group.add(hold_row)

        isolate_row = Adw.SwitchRow(
            title="Run deck entries in their own systemd unit",
            subtitle="systemd-run --user: eigene cgroup, damit ein LLM-Server "
                     "das Dashboard nicht ausbremst und ein Neustart ihn nicht killt",
        )
        isolate_row.set_active(self._settings.get("isolate_launches", True))
        isolate_row.connect("notify::active", self._on_isolate_launches)
        group.add(isolate_row)

        # Theme: sofort wirksam, wie die Schalter darueber. Die Liste kommt
        # aus theme.available(); "omarchy" steht nur drin, wenn die
        # colors.toml des aktiven Omarchy-Themes existiert.
        choices = theme_mod.available()
        self._theme_ids = [tid for tid, _ in choices]
        self._theme_row = Adw.ComboRow(
            title="Colour theme",
            subtitle="Palette aus xeneon_edge/themes/ — wirkt sofort",
            model=Gtk.StringList.new([name for _, name in choices]),
        )
        current = str(self._settings.get("theme") or theme_mod.DEFAULT)
        if current in self._theme_ids:
            self._theme_row.set_selected(self._theme_ids.index(current))
        self._theme_row.connect("notify::selected", self._on_theme)
        group.add(self._theme_row)

        app_slots, macro_slots = config_store.deck_split(self._settings)
        self._split_row = Adw.SpinRow(
            title="Deck slots reserved for apps",
            subtitle=self._split_subtitle(app_slots, macro_slots),
            adjustment=Gtk.Adjustment(
                lower=0, upper=config_store.DECK_SLOTS, step_increment=1,
                page_increment=3, value=app_slots,
            ),
        )
        self._split_row.connect("notify::value", self._on_deck_split)
        group.add(self._split_row)

        # Chart-Panel. Eigene Gruppe, weil die Erklaerung nicht in eine
        # EntryRow passt (AdwEntryRow hat keinen Untertitel).
        chart_grp = Adw.PreferencesGroup(
            title="Chart",
            description="Das eingebettete Widget ist anonym und kennt keine "
                        "gespeicherten Layouts. „Anmelden / Chart waehlen“ oeffnet ein "
                        "Browser-Fenster auf dem Hauptmonitor: dort anmelden, den "
                        "gewuenschten Chart oeffnen und „Als Chart uebernehmen“ druecken. "
                        "Das Panel haengt sich danach selbst um.",
        )
        page.add(chart_grp)

        # Kein Eingabefeld: am 2560x720-Streifen haengt ueblicherweise keine
        # Tastatur, eine URL waere dort nicht eintippbar. Der Button oeffnet
        # stattdessen das Login-Fenster, das die URL selbst eintraegt.
        self._chart_row = Adw.ActionRow(title="TradingView chart")
        self._chart_row.set_subtitle(self._chart_subtitle())

        self._chart_reset_btn = Gtk.Button(label="Widget")
        self._chart_reset_btn.set_valign(Gtk.Align.CENTER)
        self._chart_reset_btn.set_tooltip_text(
            "Zurueck auf das anonyme BTC/USDT-Widget")
        self._chart_reset_btn.connect("clicked", self._on_chart_reset)
        self._chart_row.add_suffix(self._chart_reset_btn)

        self._chart_login_btn = Gtk.Button(label="Anmelden / Chart waehlen…")
        self._chart_login_btn.set_valign(Gtk.Align.CENTER)
        self._chart_login_btn.add_css_class("suggested-action")
        self._chart_login_btn.connect("clicked", self._on_open_login)
        self._chart_row.add_suffix(self._chart_login_btn)

        chart_grp.add(self._chart_row)

        self.add(page)

    @staticmethod
    def _split_subtitle(app_slots: int, macro_slots: int) -> str:
        return (f"{app_slots} apps + {macro_slots} macros "
                f"= {config_store.DECK_SLOTS} buttons "
                f"({config_store.DECK_COLS}×{config_store.DECK_ROWS} grid)")

    def _on_deck_split(self, row, _pspec) -> None:
        self._settings["deck_app_slots"] = int(row.get_value())
        config_store.save_settings(self._settings)
        app_slots, macro_slots = config_store.deck_split(self._settings)
        row.set_subtitle(self._split_subtitle(app_slots, macro_slots))
        # Beide Tabs neu aufbauen: sie zeigen genau so viele Slots, wie das
        # Deck auch wirklich rendert.
        for key in ("apps", "macros"):
            self._refill_group(key)

    def _on_autostart(self, row, _pspec) -> None:
        self._settings["auto_start"] = bool(row.get_active())
        if self._settings["auto_start"]:
            config_store.install_autostart(ROOT / "run.sh")
        else:
            config_store.uninstall_autostart()
        config_store.save_settings(self._settings)

    def _on_theme(self, row, _pspec) -> None:
        idx = row.get_selected()
        if not (0 <= idx < len(self._theme_ids)):
            return
        theme_id = self._theme_ids[idx]
        if theme_id == self._settings.get("theme"):
            return
        self._settings["theme"] = theme_id
        config_store.save_settings(self._settings)
        if self._on_theme_cb is not None:
            try:
                self._on_theme_cb(theme_id)
            except Exception as e:
                print(f"[xeneon-edge] theme callback failed: {e}")

    def _on_hold_to_confirm(self, row, _pspec) -> None:
        self._settings["hold_to_confirm"] = bool(row.get_active())
        config_store.save_settings(self._settings)

    def _on_isolate_launches(self, row, _pspec) -> None:
        self._settings["isolate_launches"] = bool(row.get_active())
        config_store.save_settings(self._settings)

    def _chart_subtitle(self) -> str:
        url = (self._settings.get("chart_url") or "").strip()
        return url or "Widget (anonym, BTC/USDT) — kein Login"

    def _on_open_login(self, _btn) -> None:
        """scripts/tradingview-login.py starten und auf sein Ende warten.

        Das Fenster laeuft als eigener Prozess auf dem Hauptmonitor, wo
        Tastatur und Maus sind: anmelden, Chart oeffnen, "Als Chart
        uebernehmen" — das schreibt chart_url. Wenn es sich beendet, lesen wir
        die Settings neu und haengen das Panel um, ohne dass hier noch jemand
        etwas anklicken muss.
        """
        script = ROOT / "scripts" / "tradingview-login.py"
        if not script.exists():
            self._chart_row.set_subtitle(f"Skript fehlt: {script}")
            return
        argv = [sys.executable, str(script)]
        # Eigene cgroup: als Kindprozess liefe das Login-Fenster samt seinem
        # WebKit-Stapel (rund 1 GB) in der Dashboard-Unit und triebe deren
        # Speicherspitze hoch. --scope haelt es als Kind von systemd-run, also
        # bleibt wait_async() unten wie gehabt.
        if shutil.which("systemd-run"):
            argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                    f"--unit=xeneon-login-{os.getpid()}", "--"] + argv
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except GLib.Error as e:
            self._chart_row.set_subtitle(f"Start fehlgeschlagen: {e.message}")
            return
        self._chart_login_btn.set_sensitive(False)
        self._chart_row.set_subtitle("Login-Fenster offen — dort den Chart waehlen…")
        proc.wait_async(None, self._on_login_done)

    def _on_login_done(self, proc, result) -> None:
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        self._chart_login_btn.set_sensitive(True)
        # Das Login-Fenster schreibt direkt in die settings.json, also die
        # Arbeitskopie hier verwerfen statt sie drueberzuschreiben.
        self._settings = config_store.load_settings()
        self._chart_row.set_subtitle(self._chart_subtitle())
        self._on_apply_cb()

    def _on_chart_reset(self, _btn) -> None:
        self._settings["chart_url"] = ""
        config_store.save_settings(self._settings)
        self._chart_row.set_subtitle(self._chart_subtitle())
        self._on_apply_cb()

    # ----- Apps / Macros tabs -----

    def _build_entries(self, title: str, key: str) -> None:
        page = Adw.PreferencesPage(
            title=title,
            icon_name="application-x-executable-symbolic" if key == "apps" else "system-run-symbolic",
        )
        self._pages[key] = page

        # Top action bar (Apply / Cancel + dirty status)
        action_grp = Adw.PreferencesGroup()
        page.add(action_grp)
        self._action_groups[key] = action_grp

        action_row = Adw.ActionRow(title="Pending changes")
        action_row.set_subtitle("No unsaved changes")
        self._action_status[key] = action_row

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.set_valign(Gtk.Align.CENTER)
        cancel_btn.add_css_class("flat")
        cancel_btn.connect("clicked", lambda *_: self._cancel(key))
        cancel_btn.set_sensitive(False)
        self._cancel_btns[key] = cancel_btn

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.set_valign(Gtk.Align.CENTER)
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", lambda *_: self._apply(key))
        apply_btn.set_sensitive(False)
        self._apply_btns[key] = apply_btn

        action_row.add_suffix(cancel_btn)
        action_row.add_suffix(apply_btn)
        action_grp.add(action_row)

        # Slots group
        self._refill_group(key)
        self.add(page)

    def _slot_count(self, key: str) -> int:
        """Sichtbare Slots = was das Deck von dieser Kategorie auch rendert."""
        app_slots, macro_slots = config_store.deck_split(self._settings)
        return app_slots if key == "apps" else macro_slots

    def _refill_group(self, key: str) -> None:
        page = self._pages[key]
        old = self._slot_groups.get(key)
        if old is not None:
            page.remove(old)
        title = "Apps" if key == "apps" else "Macros"
        count = self._slot_count(key)
        group = Adw.PreferencesGroup(
            title=f"{title} ({count} slots — use ↑/↓ to reorder, X to clear)")
        page.add(group)
        self._slot_groups[key] = group

        if count == 0:
            other = "macros" if key == "apps" else "apps"
            empty = Adw.ActionRow(
                title=f"No slots — the whole deck is {other}",
                subtitle="Change “Deck slots reserved for apps” on the General tab",
            )
            empty.set_sensitive(False)
            group.add(empty)
            return

        # Nur bis `count` auffuellen. Bereits vorhandene Eintraege darueber
        # hinaus bleiben in der Liste stehen: wer den Regler runter- und wieder
        # hochdreht, findet seine Eintraege unveraendert vor.
        entries = self._working.setdefault(key, [])
        while len(entries) < count:
            entries.append(_empty_slot(key, len(entries)))

        for i in range(count):
            row = self._make_entry_row(key, i, entries[i])
            group.add(row)

    def _set_dirty(self, key: str, dirty: bool = True) -> None:
        self._dirty[key] = dirty
        self._cancel_btns[key].set_sensitive(dirty)
        self._apply_btns[key].set_sensitive(dirty)
        status = self._action_status[key]
        status.set_subtitle("Unsaved changes — click Apply to save"
                            if dirty else "No unsaved changes")

    # ----- Slot row -----

    def _make_entry_row(self, key: str, idx: int, entry: dict) -> Adw.ExpanderRow:
        row = Adw.ExpanderRow(
            title=entry.get("label") or f"slot {idx+1}",
            subtitle=entry.get("command") or "(empty)",
        )

        # Reorder buttons
        up = Gtk.Button.new_from_icon_name("go-up-symbolic")
        up.add_css_class("flat"); up.set_valign(Gtk.Align.CENTER)
        up.set_tooltip_text("Move up")
        up.set_sensitive(idx > 0)
        up.connect("clicked", lambda *_: self._swap(key, idx, idx - 1))
        row.add_prefix(up)

        down = Gtk.Button.new_from_icon_name("go-down-symbolic")
        down.add_css_class("flat"); down.set_valign(Gtk.Align.CENTER)
        down.set_tooltip_text("Move down")
        down.set_sensitive(idx < self._slot_count(key) - 1)
        down.connect("clicked", lambda *_: self._swap(key, idx, idx + 1))
        row.add_prefix(down)

        # Delete (X) — clears slot
        is_empty = not (entry.get("label") or entry.get("command"))
        delete = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
        delete.add_css_class("flat"); delete.add_css_class("destructive-action")
        delete.set_valign(Gtk.Align.CENTER)
        delete.set_tooltip_text("Clear this slot")
        delete.set_sensitive(not is_empty)
        delete.connect("clicked", lambda *_: self._delete(key, idx))
        row.add_suffix(delete)

        # Editable fields
        label_entry = Adw.EntryRow(title="Label")
        label_entry.set_text(entry.get("label") or "")
        cmd_entry = Adw.EntryRow(title="Command")
        cmd_entry.set_text(entry.get("command") or "")
        args_entry = Adw.EntryRow(title="Args")
        args_entry.set_text(entry.get("args") or "")
        icon_entry = Adw.EntryRow(title="Icon (optional theme-name or path)")
        icon_entry.set_text(entry.get("icon") or "")
        confirm_row = Adw.SwitchRow(title="Confirm before run (hold-to-confirm)")
        confirm_row.set_active(bool(entry.get("confirm")))

        browse = Gtk.Button(label="Browse…", valign=Gtk.Align.CENTER)
        browse.add_css_class("flat")
        browse.connect("clicked", lambda *_: self._browse_for(cmd_entry))
        cmd_entry.add_suffix(browse)

        def commit(*_a):
            entry["label"] = label_entry.get_text().strip()
            entry["command"] = cmd_entry.get_text().strip()
            entry["args"] = args_entry.get_text().strip()
            ic = icon_entry.get_text().strip()
            if ic:
                entry["icon"] = ic
            else:
                entry.pop("icon", None)
            entry["confirm"] = bool(confirm_row.get_active())
            entry.setdefault("accent", "#ff0033")
            entry.setdefault("kind", key[:-1])
            entry.setdefault("id", f"{key[:-1]}{idx+1}")
            row.set_title(entry["label"] or f"slot {idx+1}")
            row.set_subtitle(entry["command"] or "(empty)")
            arr = self._working.setdefault(key, [])
            while len(arr) <= idx:
                arr.append(_empty_slot(key, len(arr)))
            arr[idx] = entry
            empty = not (entry["label"] or entry["command"])
            delete.set_sensitive(not empty)
            self._set_dirty(key, True)

        for w in (label_entry, cmd_entry, args_entry, icon_entry):
            w.connect("changed", commit)
        confirm_row.connect("notify::active", lambda *_: commit())

        row.add_row(label_entry)
        row.add_row(cmd_entry)
        row.add_row(args_entry)
        row.add_row(icon_entry)
        row.add_row(confirm_row)
        return row

    # ----- Mutations on the working copy -----

    def _swap(self, key: str, i: int, j: int) -> None:
        count = self._slot_count(key)
        if i == j or not (0 <= i < count and 0 <= j < count):
            return
        arr = self._working.setdefault(key, [])
        while len(arr) < count:
            arr.append(_empty_slot(key, len(arr)))
        arr[i], arr[j] = arr[j], arr[i]
        self._set_dirty(key, True)
        self._refill_group(key)

    def _delete(self, key: str, idx: int) -> None:
        arr = self._working.setdefault(key, [])
        while len(arr) <= idx:
            arr.append(_empty_slot(key, len(arr)))
        arr[idx] = _empty_slot(key, idx)
        self._set_dirty(key, True)
        self._refill_group(key)

    # ----- Apply / Cancel -----

    def _apply(self, key: str, *, toast: bool = True) -> None:
        self._apps_data[key] = copy.deepcopy(self._working.get(key, []))
        config_store.save_apps(self._apps_data)
        self._set_dirty(key, False)
        try:
            self._on_apply_cb()
        except Exception as e:
            print(f"[xeneon-edge] settings apply callback failed: {e}")
        if toast:
            self.add_toast(Adw.Toast.new(f"{key.capitalize()} saved"))

    def _cancel(self, key: str) -> None:
        self._working[key] = copy.deepcopy(self._apps_data.get(key, []))
        self._set_dirty(key, False)
        self._refill_group(key)
        self.add_toast(Adw.Toast.new(f"{key.capitalize()} reverted"))

    # ----- File picker -----

    def _browse_for(self, target: Adw.EntryRow) -> None:
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Pick executable")
        initial = Gio.File.new_for_path("/usr/bin")
        dialog.set_initial_folder(initial)
        dialog.open(self, None, self._on_browse_done, target)

    def _on_browse_done(self, dialog: Gtk.FileDialog, result, target: Adw.EntryRow) -> None:
        try:
            file = dialog.open_finish(result)
        except Exception:
            return
        if file is None:
            return
        path = file.get_path()
        if path:
            target.set_text(path)

    def _on_close(self, *_a) -> bool:
        # Frueher hat Schliessen alle nicht per Apply bestaetigten Aenderungen
        # kommentarlos verworfen. Der Apply-Button steht pro Tab ganz oben und
        # ist beim Scrollen durch 18 Slots laengst aus dem Bild — wer unten
        # fertig wird und auf X klickt, verlor seine Eintraege.
        pending = [k for k in ("apps", "macros") if self._dirty.get(k)]
        if pending and not self._force_close:
            self._confirm_close(pending)
            return True  # Schliessen erstmal abbrechen

        # General settings were saved as the user toggled them.
        # Always rebuild the deck in case General settings changed.
        try:
            self._on_apply_cb()
        except Exception as e:
            print(f"[xeneon-edge] settings close callback failed: {e}")
        return False

    def _confirm_close(self, pending: list[str]) -> None:
        names = " und ".join(k.capitalize() for k in pending)
        dlg = Adw.AlertDialog(
            heading="Ungespeicherte Änderungen",
            body=f"{names} {'haben' if len(pending) > 1 else 'hat'} "
                 f"ungespeicherte Änderungen.",
        )
        dlg.add_response("back", "Zurück")
        dlg.add_response("discard", "Verwerfen")
        dlg.add_response("save", "Speichern")
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("save")
        dlg.set_close_response("back")
        dlg.connect("response", self._on_confirm_close_response, pending)
        dlg.present(self)

    def _on_confirm_close_response(self, _dlg, response: str,
                                   pending: list[str]) -> None:
        if response == "back":
            return
        if response == "save":
            for key in pending:
                self._apply(key, toast=False)
        else:  # discard
            for key in pending:
                self._working[key] = copy.deepcopy(self._apps_data.get(key, []))
                self._set_dirty(key, False)
        self._force_close = True
        self.close()
