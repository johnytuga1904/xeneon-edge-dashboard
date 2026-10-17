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

# Shown by --help; the module docstring above stays the German design note.
_HELP = """Adapt Omarchy's notifications to the dashboard.

Patches a clone of the Omarchy shell's notification plugin
(~/.config/omarchy/plugins/<user>.notifications/): toasts no longer appear
on the Xeneon Edge strip, and every card gets a close x at the top right.
The original under /usr/share/omarchy stays untouched. The script is
idempotent; after a larger Omarchy update run --revert and then the script
again so the clone sits on the current original.
"""

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
        "    // No toasts on the dashboard strip: Omarchy builds one PanelWindow\n"
        "    // per output, so the toast would otherwise land right above the\n"
        "    // deck buttons.\n"
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
            "  // Close x at the top right. Opt-in, because the same card also\n"
            "  // renders the history panel — closeRequested is not wired up there,\n"
            "  // so the button would be dead.\n"
            "  property bool closable: false\n",
            "  property bool closable: false\n",
        ),
        (
            "components/NotificationCard.qml",
            "      Layout.rightMargin: Style.space(12)\n",
            "      // Room for the close x in the top right corner.\n"
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


CLOSE_BUTTON_QML = """  // Declared after mainColumn and therefore above the card-wide MouseArea:
  // otherwise the click falls through to onCardClicked and triggers the
  // notification's default action instead of closing it.
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
      // Dimmed until the pointer is on the card, opaque on the button
      // itself: findable without stealing the show from the summary.
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
    ap = argparse.ArgumentParser(description=_HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monitor", default="",
                    help="the dashboard's connector (default: target_monitor from settings.json)")
    ap.add_argument("--only", default="",
                    help="toasts only on this connector (default: everything except the dashboard)")
    ap.add_argument("--check", action="store_true", help="only check, change nothing")
    ap.add_argument("--revert", action="store_true", help="remove the clone, re-enable the original")
    args = ap.parse_args()

    if not shutil.which("omarchy"):
        bad("omarchy not found — this script is for Omarchy only.")
        return 1

    target = plugin_dir()

    if args.revert:
        say("Back to the original")
        if not target.exists():
            warn(f"{target} does not exist — nothing to do")
            return 0
        run("omarchy", "plugin", "remove", target.name, "--yes")
        run("omarchy", "plugin", "enable", SOURCE_ID)
        run("omarchy", "restart", "shell")
        ok(f"{target.name} removed, {SOURCE_ID} active again")
        return 0

    dashboard = dashboard_monitor(args.monitor)
    if not dashboard:
        bad("No dashboard monitor known — pass --monitor or run")
        bad("  install-arch.sh first (it writes target_monitor).")
        return 1

    say("Plugin clone")
    if target.exists():
        ok(f"{target} already exists")
    elif args.check:
        warn(f"{target} is missing — would clone {SOURCE_ID}")
        return 0
    else:
        r = run("omarchy", "plugin", "clone", SOURCE_ID)
        if r.returncode != 0:
            bad(f"omarchy plugin clone {SOURCE_ID} failed:")
            bad(f"  {(r.stderr or r.stdout).strip()}")
            return 1
        ok(f"{SOURCE_ID} -> {target.name}")

    say(f"Changes (dashboard: {dashboard}"
        + (f", toasts only on {args.only}" if args.only else ", toasts on all others") + ")")

    pending: list[tuple[Path, str, str]] = []
    for rel, anchor, replacement, applied in edits(dashboard, args.only):
        path = target / rel
        if not path.exists():
            bad(f"{rel} is missing in the clone")
            return 1
        text = path.read_text()
        if applied in text:
            ok(f"{rel}: already applied")
            continue
        if anchor not in text:
            bad(f"{rel}: anchor not found — Omarchy has changed this spot.")
            bad(f"  Looked for: {anchor.strip().splitlines()[0][:70]}")
            bad("  Run --revert first, then clone again and update this spot in the script.")
            return 1
        if text.count(anchor) != 1:
            bad(f"{rel}: anchor found {text.count(anchor)}x, expected exactly 1")
            return 1
        pending.append((path, anchor, replacement))
        (warn if args.check else ok)(f"{rel}: {'would patch' if args.check else 'patched'}")

    if args.check:
        return 0

    for path, anchor, replacement in pending:
        path.write_text(path.read_text().replace(anchor, replacement, 1))

    say("Restarting the shell")
    run("omarchy", "restart", "shell")
    ok("omarchy restart shell")
    print()
    say("Done")
    print(f"  Clone:     {target}")
    print(f"  Revert:    {Path(__file__).name} --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
