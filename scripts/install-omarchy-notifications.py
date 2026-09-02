#!/usr/bin/env python3
"""Omarchy-Notifications an das Dashboard anpassen.

Zwei Aenderungen am Notification-Plugin der Omarchy-Shell:

1. Toasts nicht mehr auf dem Xeneon Edge. Omarchy legt eine PanelWindow pro
   Output an (``Variants { model: Quickshell.screens }``), also erscheint jeder
   Toast auch auf dem 2560x720-Streifen — dort direkt ueber den Deck-Buttons,
   und weggeklickt werden kann er am Streifen ohnehin schlecht.

2. Ein Schliess-x oben rechts auf der Karte. Das Signal dafuer
   (``closeRequested`` -> ``dismissPopup``) ist in Omarchy schon verdrahtet, es
   gab bisher nur keinen sichtbaren Knopf: geschlossen wurde per Rechtsklick.

Beides passiert in einem *Klon* des Plugins unter
``~/.config/omarchy/plugins/<user>.notifications/`` — das Original unter
/usr/share/omarchy bleibt unangetastet und Omarchy-Updates fassen den Klon
nicht an. Preis dafuer: der Klon friert den Stand von Omarchy ein, aus dem er
geklont wurde. Nach einem groesseren Omarchy-Update also einmal
``--revert`` und das Skript neu laufen lassen, damit der Klon wieder auf dem
aktuellen Original sitzt.

Das Skript ist idempotent: schon angewandte Aenderungen werden erkannt und
uebersprungen. Passt ein Anker nicht mehr (Omarchy hat die Stelle umgebaut),
bricht es mit genau dieser Stelle ab, statt still etwas Halbes zu hinterlassen.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGINS_DIR = Path.home() / ".config" / "omarchy" / "plugins"
SETTINGS_FILE = Path.home() / ".config" / "xeneon-edge" / "settings.json"
SOURCE_ID = "omarchy.notifications"

RED = "\033[1;31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"; OFF = "\033[0m"


def say(msg: str) -> None:   print(f"{RED}> {msg}{OFF}")
def ok(msg: str) -> None:    print(f"  {GREEN}v{OFF} {msg}")
def warn(msg: str) -> None:  print(f"  {YELLOW}!{OFF} {msg}")
def bad(msg: str) -> None:   print(f"  {RED}x{OFF} {msg}")


def plugin_dir() -> Path:
    return PLUGINS_DIR / f"{os.environ.get('USER', 'user')}.notifications"


def dashboard_monitor(explicit: str) -> str:
    """Connector des Dashboards: Argument, sonst target_monitor aus settings.json."""
    if explicit:
        return explicit
    try:
        return str(json.loads(SETTINGS_FILE.read_text()).get("target_monitor", "") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def screens_expression(dashboard: str, only: str) -> str:
    """Der QML-Ausdruck fuer das Variants-Modell der Toast-Fenster.

    Mit --only wird der Monitor fest gesetzt, aber mit Rueckfallebene: haengt
    der gerade nicht dran, gehen die Toasts auf alles ausser dem Streifen,
    statt komplett auszubleiben.
    """
    if only:
        return (
            "    model: {\n"
            f'      const main = Quickshell.screens.filter(s => s.name === "{only}")\n'
            f'      return main.length > 0 ? main : Quickshell.screens.filter(s => s.name !== "{dashboard}")\n'
            "    }\n"
        )
    return f'    model: Quickshell.screens.filter(s => s.name !== "{dashboard}")\n'


# Jede Aenderung: (Datei, Anker im Original, Ersatz). `applied` erkennt einen
# schon gepatchten Baum, damit ein zweiter Lauf nichts doppelt einfuegt.
def edits(dashboard: str, only: str) -> list[tuple[str, str, str, str]]:
    header = (
        "    // Toasts nicht auf dem Dashboard-Streifen: Omarchy baut ein\n"
        "    // PanelWindow pro Output, der Toast landet dort sonst direkt ueber\n"
        "    // den Deck-Buttons.\n"
    )
    return [
        (
            "Service.qml",
            "  Variants {\n    model: Quickshell.screens\n",
            "  Variants {\n" + header + screens_expression(dashboard, only),
            # Marker bewusst ohne Kommentartext: der Code ist die Aenderung,
            # der Kommentar darf sich aendern, ohne dass ein zweiter Lauf
            # doppelt patcht.
            "Quickshell.screens.filter",
        ),
        (
            "Service.qml",
            "              cornerRadius: service.cornerRadius\n",
            "              cornerRadius: service.cornerRadius\n              closable: true\n",
            "              closable: true\n",
        ),
        (
            "components/NotificationCard.qml",
            "  readonly property bool hovered: hoverTracker.hovered\n",
            "  readonly property bool hovered: hoverTracker.hovered\n"
            "\n"
            "  // Schliess-x oben rechts. Opt-in, weil dieselbe Karte auch das\n"
            "  // History-Panel rendert — dort ist closeRequested nicht verdrahtet,\n"
            "  // der Knopf waere also tot.\n"
            "  property bool closable: false\n",
            "  property bool closable: false\n",
        ),
        (
            "components/NotificationCard.qml",
            "      Layout.rightMargin: Style.space(12)\n",
            "      // Platz fuer das Schliess-x in der oberen rechten Ecke.\n"
            "      Layout.rightMargin: root.closable ? Style.space(26) : Style.space(12)\n",
            "root.closable ? Style.space(26)",
        ),
        (
            "components/NotificationCard.qml",
            "      }\n    }\n  }\n\n}\n",
            "      }\n    }\n  }\n\n" + CLOSE_BUTTON_QML + "}\n",
            "id: closeButton",
        ),
    ]


CLOSE_BUTTON_QML = """  // Nach mainColumn deklariert und damit ueber der kartenweiten MouseArea:
  // sonst faellt der Klick durch auf onCardClicked und loest die
  // Default-Aktion der Notification aus, statt sie zu schliessen.
  Item {
    id: closeButton
    visible: root.closable
    width: Style.space(18)
    height: Style.space(18)
    anchors.top: parent.top
    anchors.right: parent.right
    anchors.topMargin: root.borderTop + Style.space(4)
    anchors.rightMargin: root.borderRight + Style.space(4)

    Text {
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: "\\u00d7"
      color: Color.notifications.text
      font.family: "Liberation Sans"
      font.pixelSize: Style.font.heading
      // Gedimmt, bis der Zeiger auf der Karte ist, deckend auf dem Knopf
      // selbst: auffindbar, ohne der Summary die Schau zu stehlen.
      opacity: closeHover.hovered ? 1.0 : (root.hovered ? 0.75 : 0.35)
      Behavior on opacity { NumberAnimation { duration: 100 } }
    }

    HoverHandler {
      id: closeHover
      cursorShape: Qt.PointingHandCursor
    }

    MouseArea {
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton
      onClicked: root.closeRequested()
    }
  }
"""


def run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monitor", default="",
                    help="Connector des Dashboards (Default: target_monitor aus settings.json)")
    ap.add_argument("--only", default="",
                    help="Toasts nur auf diesem Connector (Default: alles ausser dem Dashboard)")
    ap.add_argument("--check", action="store_true", help="nur pruefen, nichts aendern")
    ap.add_argument("--revert", action="store_true", help="Klon entfernen, Original wieder aktivieren")
    args = ap.parse_args()

    if not shutil.which("omarchy"):
        bad("omarchy nicht gefunden — das Skript ist nur fuer Omarchy.")
        return 1

    target = plugin_dir()

    if args.revert:
        say("Zurueck auf das Original")
        if not target.exists():
            warn(f"{target} existiert nicht — nichts zu tun")
            return 0
        run("omarchy", "plugin", "remove", target.name, "--yes")
        run("omarchy", "plugin", "enable", SOURCE_ID)
        run("omarchy", "restart", "shell")
        ok(f"{target.name} entfernt, {SOURCE_ID} wieder aktiv")
        return 0

    dashboard = dashboard_monitor(args.monitor)
    if not dashboard:
        bad("Kein Dashboard-Monitor bekannt — --monitor setzen oder erst")
        bad("  install-arch.sh laufen lassen (schreibt target_monitor).")
        return 1

    say("Plugin-Klon")
    if target.exists():
        ok(f"{target} existiert bereits")
    elif args.check:
        warn(f"{target} fehlt — wuerde {SOURCE_ID} klonen")
        return 0
    else:
        r = run("omarchy", "plugin", "clone", SOURCE_ID)
        if r.returncode != 0:
            bad(f"omarchy plugin clone {SOURCE_ID} fehlgeschlagen:")
            bad(f"  {(r.stderr or r.stdout).strip()}")
            return 1
        ok(f"{SOURCE_ID} -> {target.name}")

    say(f"Anpassungen (Dashboard: {dashboard}"
        + (f", Toasts nur auf {args.only}" if args.only else ", Toasts auf allen anderen") + ")")

    pending: list[tuple[Path, str, str]] = []
    for rel, anchor, replacement, applied in edits(dashboard, args.only):
        path = target / rel
        if not path.exists():
            bad(f"{rel} fehlt im Klon")
            return 1
        text = path.read_text()
        if applied in text:
            ok(f"{rel}: schon angewandt")
            continue
        if anchor not in text:
            bad(f"{rel}: Anker nicht gefunden — Omarchy hat die Stelle umgebaut.")
            bad(f"  Gesucht: {anchor.strip().splitlines()[0][:70]}")
            bad("  Erst --revert, dann neu klonen und diese Stelle im Skript nachziehen.")
            return 1
        if text.count(anchor) != 1:
            bad(f"{rel}: Anker {text.count(anchor)}x vorhanden, erwartet genau 1")
            return 1
        pending.append((path, anchor, replacement))
        (warn if args.check else ok)(f"{rel}: {'wuerde patchen' if args.check else 'gepatcht'}")

    if args.check:
        return 0

    for path, anchor, replacement in pending:
        path.write_text(path.read_text().replace(anchor, replacement, 1))

    say("Shell neu starten")
    run("omarchy", "restart", "shell")
    ok("omarchy restart shell")
    print()
    say("Fertig")
    print(f"  Klon:      {target}")
    print(f"  Zurueck:   {Path(__file__).name} --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
