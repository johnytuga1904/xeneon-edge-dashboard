#!/usr/bin/env python3
"""Editor — Layout, Modul-Einstellungen, Deck und Settings in einem Fenster.

Das Dashboard laeuft im Vollbild auf einem 2560x720-Streifen, an dem
ueblicherweise weder Tastatur noch Maus haengen. Dieses Skript oeffnet den
Editor deshalb auf dem Hauptmonitor — dasselbe Muster wie
scripts/tradingview-login.py. Das Zahnrad auf dem Streifen startet es.

    ./scripts/layout-editor.py

Gespeichert wird nach ~/.config/xeneon-edge/{layout,settings,apps}.json. Ein
laufendes Dashboard beobachtet die Dateien und uebernimmt alles ohne Neustart.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
from pathlib import Path

# Wie in run.sh: XENEON_WEBKIT_DMABUF=0 schaltet auf WebKits Shared-Memory-
# Renderer, fuer Multi-GPU-Systeme mit schwarzer WebKit-Flaeche. Der Editor
# wird direkt aufgerufen, hat also nicht das Environment aus run.sh.
if os.environ.get("XENEON_WEBKIT_DMABUF") == "0":
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib  # noqa: E402

from xeneon_edge import config_store, editor, theme  # noqa: E402
from xeneon_edge.paths import ROOT  # noqa: E402
from xeneon_edge.ui import monitors  # noqa: E402
from xeneon_edge.ui.chart import import_webkit  # noqa: E402

BRIDGE = "bridge"


def stage_geometry(display: Gdk.Display, preferred: str) -> dict:
    """Groesse des Zielmonitors — die Bezugsflaeche des Editors.

    Ohne erkannten Streifen bleibt es bei der Geometrie, fuer die das Dashboard
    entworfen ist: der Editor braucht *eine* Bezugsbreite, sonst kann er keine
    Proportionen zeichnen.
    """
    monitor = monitors.find_target_monitor(display, preferred)
    if monitor is None:
        return dict(editor.FALLBACK_STAGE)
    g = monitor.get_geometry()
    return {"width": g.width, "height": g.height,
            "connector": monitors._connector_name(monitor)}


class EditorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, WebKit, page: str):
        super().__init__(application=app, title="Xeneon Edge — Einstellungen")
        # Auf den Inhalt abgestimmt: Kopfleiste, Buehne im Seitenverhaeltnis
        # des Streifens ueber die volle Breite neben der Seitenleiste, darunter
        # der Hinweis. Die Hyprland-Regel aus install-arch.sh nennt dieselbe
        # Groesse.
        self.set_default_size(1800, 640)

        ucm = WebKit.UserContentManager()
        # WebKit 6.0 will einen World-Namen, aeltere Bindings nicht.
        try:
            ucm.register_script_message_handler(BRIDGE, None)
        except TypeError:
            ucm.register_script_message_handler(BRIDGE)
        ucm.connect(f"script-message-received::{BRIDGE}", self._on_message)

        self.view = WebKit.WebView(user_content_manager=ucm)
        self.view.set_hexpand(True)
        self.view.set_vexpand(True)
        self.set_child(self.view)
        # Kein network_session: der Editor laedt nichts nach und soll sich
        # nicht in das Browserprofil des Chart-Panels einmischen.
        self.view.load_html(page, "xeneon-edge:editor")
        # Laufendes Login-Fenster und der Stand von chart_url davor, damit
        # Abbrechen nicht wie Erfolg aussieht.
        self._login_proc: Gio.Subprocess | None = None
        self._login_before: tuple[str, float] = ("", 0.0)

    # ----- Seite -> Python -----

    def _on_message(self, _ucm, js_value) -> None:
        try:
            raw = js_value.to_json(0)
        except Exception:
            raw = js_value.to_string()
        # postMessage schickt einen String, der als JSON-String ankommt —
        # also einmal auspacken, bevor das eigentliche Objekt dran ist.
        try:
            unwrapped = json.loads(raw)
            if isinstance(unwrapped, str):
                raw = unwrapped
        except (TypeError, ValueError):
            pass

        try:
            msg = json.loads(raw)
            action, target = msg.get("action"), msg.get("target")
        except Exception:
            action = target = None

        if action == "login":
            self._open_login()
            return
        if action == "browse":
            self._browse(str(target or "program"))
            return

        result = editor.handle_message(raw)
        print(("[xeneon-edge] " if result.ok else "[xeneon-edge] FEHLER: ") + result.message)
        self._call("__saved", result.ok, result.message)

    # ----- Python -> Seite -----

    def _call(self, fn: str, *args) -> None:
        script = f"window.{fn}({', '.join(json.dumps(a) for a in args)});"
        try:
            self.view.evaluate_javascript(script, -1, None, None, None, None, None)
        except Exception as e:
            print(f"[xeneon-edge] Rueckmeldung an die Seite fehlgeschlagen: {e}")

    # ----- Login-Fenster -----

    def _open_login(self) -> None:
        """scripts/tradingview-login.py starten und auf sein Ende warten.

        Das Fenster laeuft als eigener Prozess: anmelden, Chart oeffnen, "Als
        Chart uebernehmen" — das schreibt chart_url in settings.json. Danach
        lesen wir die URL und geben sie der Seite, die sie ins ausgewaehlte
        Web-Modul traegt.
        """
        script = ROOT / "scripts" / "tradingview-login.py"
        if not script.exists():
            self._call("__login_done", "", f"Skript fehlt: {script}")
            return
        if self._login_proc is not None:
            self._call("__login_done", "", "Das Login-Fenster ist schon offen")
            return
        self._login_before = self._chart_url_state()
        argv = [sys.executable, str(script)]
        if shutil.which("systemd-run"):
            argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                    f"--unit=xeneon-login-{os.getpid()}", "--"] + argv
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except GLib.Error as e:
            self._call("__login_done", "", f"Start fehlgeschlagen: {e.message}")
            return
        self._login_proc = proc
        proc.wait_async(None, self._on_login_done)

    @staticmethod
    def _chart_url_state() -> tuple[str, float]:
        """chart_url und Aenderungszeit von settings.json."""
        url = str(config_store.load_settings().get("chart_url") or "")
        try:
            mtime = config_store.USER_SETTINGS_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        return url, mtime

    def _on_login_done(self, proc, result) -> None:
        self._login_proc = None
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        # Nur ein *neu geschriebener* chart_url zaehlt. Vorher stand hier
        # einfach der alte Wert aus settings.json — das Fenster schliessen
        # ohne "Als Chart uebernehmen" schaltete das Modul trotzdem um.
        url, mtime = self._chart_url_state()
        before_url, before_mtime = self._login_before
        if url and (url != before_url or mtime != before_mtime):
            self._call("__login_done", url, "")
        else:
            self._call("__login_done", "", "Kein Chart uebernommen")

    # ----- Datei-Picker fuer Deck-Kommandos -----

    def _browse(self, target: str = "program") -> None:
        """``target="dir"`` waehlt einen Ordner im Home (Musikordner),
        ``"file"`` eine Datei im Home (Notizen-Modul), alles andere ein
        Programm in /usr/bin (Deck-Kommandos)."""
        dialog = Gtk.FileDialog.new()
        home = Gio.File.new_for_path(GLib.get_home_dir())
        if target == "dir":
            dialog.set_title("Ordner waehlen")
            dialog.set_initial_folder(home)
            dialog.select_folder(self, None, self._on_folder_browsed)
            return
        if target == "file":
            dialog.set_title("Datei waehlen")
            dialog.set_initial_folder(home)
        else:
            dialog.set_title("Programm waehlen")
            dialog.set_initial_folder(Gio.File.new_for_path("/usr/bin"))
        dialog.open(self, None, self._on_browsed)

    def _on_browsed(self, dialog, result) -> None:
        self._deliver(dialog.open_finish, result)

    def _on_folder_browsed(self, dialog, result) -> None:
        self._deliver(dialog.select_folder_finish, result)

    def _deliver(self, finish, result) -> None:
        """Ergebnis eines Dateidialogs an die Seite geben.

        Abbrechen wirft — und ist kein Fehler, sondern die haeufigste Antwort.
        """
        try:
            file = finish(result)
        except Exception:
            return
        path = file.get_path() if file is not None else None
        if path:
            self._call("__browsed", path)


def main() -> int:
    WebKit = import_webkit()
    if WebKit is None:
        print("WebKitGTK 6.0 fehlt — ohne das gibt es keinen Editor.")
        print("  Fedora: sudo dnf install webkitgtk6.0")
        print("  Arch:   sudo pacman -S webkitgtk-6.0")
        print("  Debian: sudo apt install gir1.2-webkit-6.0")
        return 1

    settings = config_store.load_settings()
    app = Gtk.Application(application_id="io.github.johnytuga1904.XeneonEdge.Editor")

    def on_activate(a):
        display = Gdk.Display.get_default()
        preferred = str(settings.get("target_monitor", "") or "")
        if display is not None:
            stage = stage_geometry(display, preferred)
            mons = monitors.list_monitors_for_settings(display)
        else:
            stage, mons = dict(editor.FALLBACK_STAGE), []
        palette = theme.load(settings.get("theme"))
        page = editor.build_page(editor.payload(stage=stage, palette=palette, monitors=mons))

        win = EditorWindow(a, WebKit, page)
        win.present()
        monitors.move_off_dashboard(
            win, preferred, str(settings.get("launch_monitor", "") or ""))

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
