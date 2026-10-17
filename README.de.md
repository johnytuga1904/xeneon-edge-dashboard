# Xeneon Edge Dashboard

*Diese deutsche Fassung wird nicht mehr gepflegt; massgeblich ist die
englische [README.md](README.md).*

Natives GTK4-Dashboard für Linux — Sensoren direkt aus `/proc` und `/sys`, kein Daemon, kein Electron. Entstanden als Linux-Port eines privaten Windows/WPF-Dashboards; veröffentlicht ist nur die Linux-Version.

## Features

- CPU: Last, Temperatur, Takt
- GPU: AMD (über `/sys/class/drm`) **und** NVIDIA (über `nvidia-smi`) gleichzeitig
- RAM, Netzwerk, Lüfter (alle hwmon-Sensoren)
- Top-Prozesse (psutil) — `×` gedrückt halten beendet den Prozess (SIGTERM)
- Audio: PipeWire-Lautstärke + Mute + Default-Device-Auswahl (`pactl` / `wpctl`)
- Wetter (Open-Meteo, Ort im Editor einstellbar) und nächstes Spiel eines Teams (ESPN)
- TradingView-Modul (WebKitGTK) — wahlweise das anonyme Widget mit
  einstellbarem Symbol, Intervall und Indikatoren oder die echte Chart-Seite
  mit dem eigenen Account und gespeichertem Layout
- OpenMarket-Modul — der eigene Chart aus einem OpenMarket-Account, gewählt
  im selben Login-Fenster
- Wiedergabe: was gerade spielt (MPRIS), oder ein eigener Musikordner, den
  das Dashboard selbst abspielt
- 3×6 Launch-Deck (18 Buttons) mit frei einstellbarer Aufteilung Apps/Macros,
  Hold-to-confirm für `poweroff`/`reboot`/etc.
- Auto-Start via `~/.config/autostart`

## Voraussetzungen (Fedora / Nobara)

System-Pakete (auf Nobara 43 ist das meiste schon da):

```bash
sudo dnf install gtk4 libadwaita python3-gobject \
                 lm_sensors pipewire-utils \
                 webkitgtk6.0          # für das TradingView-Chart
sudo dnf install gstreamer1-plugins-good   # autoaudiosink — sonst Absturz beim Login
sudo dnf install nvidia-smi             # nur falls NVIDIA-GPU genutzt wird
```

Python-Abhängigkeiten (empfohlen: System-Python, kein venv — wegen GTK):

```bash
pip install --user -r requirements.txt   # psutil, requests
```

## Voraussetzungen (Debian 13 / trixie)

Alles auf einmal — installiert Pakete, verifiziert, schreibt Settings + Autostart:

```bash
./scripts/install-debian.sh
```

Optionen: `--monitor DP-2` (Connector fest pinnen statt Auto-Erkennung),
`--no-autostart`, `--no-fullscreen`, `--yes` (nicht nachfragen),
`--no-packages` (nur Settings/Autostart neu schreiben), `--check` (nur prüfen,
nichts installieren).

Von Hand entspricht das:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 gir1.2-webkit-6.0 python3-psutil python3-requests \
                 lm-sensors pulseaudio-utils wireplumber \
                 gstreamer1.0-plugins-good gir1.2-gstreamer-1.0
sudo apt install nvidia-smi          # nur bei NVIDIA; liegt in 'non-free'
```

Debian-spezifisch zu beachten:

- **Kein `pip install --user`.** Debian markiert sein Python als *externally
  managed* (PEP 668) — pip bricht mit `externally-managed-environment` ab.
  `psutil` und `requests` kommen deshalb aus apt, nicht aus `requirements.txt`.
- **`gir1.2-webkit-6.0`** ist das GTK4-WebKit (trixie: 2.52). Fehlt es, zeigt
  die Chart-Spalte nur den Platzhalter — der Rest läuft normal weiter.
- **`nvidia-smi`** liegt in der `non-free`-Komponente. Falls apt es nicht
  findet, in `/etc/apt/sources.list.d/debian.sources` bei `Components:`
  `contrib non-free non-free-firmware` ergänzen.
- **Kein 2560×720-Monitor?** Dann findet die Auto-Erkennung nichts und die App
  startet im normalen Fenster auf dem Standard-Display. Zielmonitor entweder
  mit `--monitor <Connector>` setzen oder später im Editor (Einstellungen → Zielmonitor) wählen.

## Voraussetzungen (Arch / Omarchy)

Alles auf einmal — Pakete, Verify, Settings, Deck, Autostart, Hyprland-Regeln:

```bash
./scripts/install-arch.sh
```

Optionen wie beim Debian-Skript (`--monitor DP-2`, `--no-autostart`,
`--no-fullscreen`, `--yes`, `--no-packages`, `--check`), dazu
`--deck omarchy` (Deck mit Omarchy-Kommandos vorbelegen) und `--no-hypr`
(kein Fensterregel-Snippet schreiben).

Von Hand entspricht das:

```bash
sudo pacman -S --needed python-gobject python-cairo gtk4 libadwaita \
                        webkitgtk-6.0 python-psutil python-requests \
                        lm_sensors libpulse wireplumber pciutils \
                        adwaita-icon-theme xdg-desktop-portal-gtk \
                        gst-plugins-good
```

Alles liegt in `[core]`/`[extra]`, ein AUR-Helper ist nicht noetig.
`nvidia-smi` kommt aus `nvidia-utils` und haengt am Treiberpaket
(`nvidia`/`nvidia-open`/`-dkms`) — das Skript installiert es deshalb nicht
selbst, sondern meldet nur, wenn eine NVIDIA-Karte ohne `nvidia-smi` steckt
(auf Omarchy: `omarchy-install-nvidia`).

Arch-spezifisch zu beachten:

- **`gst-plugins-good`.** WebKitGTK baut fuer jedes `<audio>` und jeden
  AudioContext eine GStreamer-Pipeline und verlangt darin `autoaudiosink`
  namentlich. Bei `webkitgtk-6.0` ist das Paket nur eine *optionale*
  Abhaengigkeit, fehlt also auf einer frischen Installation. WebKit bekommt
  dann `NULL` zurueck, haengt trotzdem einen Signal-Handler daran und bricht ab
  — der `WebKitWebProcess` stirbt reproduzierbar mit SIGABRT, sobald
  TradingView Ton anfasst. Ein vorhandenes `pipewiresink` hilft nicht, der Name
  wird hart gesucht.
- **Kein `pip install --user`** — wie Debian markiert Arch sein Python als
  *externally managed* (PEP 668). `psutil` und `requests` kommen aus pacman,
  `requirements.txt` bleibt fuer venv-Setups liegen.
- **Kein `pacman -Sy <paket>`.** Ein Teil-Upgrade ist auf Arch der uebliche Weg
  in kaputte Abhaengigkeiten; das Skript installiert mit `-S --needed` gegen die
  vorhandene Datenbank und verweist bei einem Fehlschlag auf `sudo pacman -Syu`.
- **`GDK_SCALE`.** Omarchy setzt in `~/.config/hypr/monitors.conf`
  session-weit `env = GDK_SCALE,2` (bzw. `hl.env("GDK_SCALE", ...)` in der
  Lua-Variante). Die Spaltenbreiten des Dashboards sind harte Pixel fuer
  2560x720 — bei Buffer-Scale 2 ist nur noch ein Viertel des Layouts im Bild.
  `run.sh` exportiert deshalb `GDK_SCALE=1` fuer den eigenen Prozess;
  ueberschreibbar mit `XENEON_GDK_SCALE=2 ./run.sh`.
- **Zwei Grafikkarten, eine davon NVIDIA.** Haengt die Anzeige an einer AMD-
  (oder Intel-)Karte und steckt daneben eine NVIDIA (etwa fuer LLMs), laedt
  jedes EGL-Programm zuerst den NVIDIA-Treiber: GLVND listet `10_nvidia.json`
  vor `50_mesa.json`, und WebKit nimmt den ersten Render-Knoten, meist
  `renderD128` = NVIDIA. Der Web-Prozess des Charts rendert dann ueber einen
  Treiber, der mit der Anzeige nichts zu tun hat — `libnvidia-eglcore` ist
  hier viermal an derselben Adresse abgestuerzt (Treiber 610.57, Oktober
  2026). WebKitGTK 2.52 kennt keine Variable fuer den Render-Knoten, deshalb
  beschraenkt `xeneon_edge/webkit_env.py` GLVND auf die Mesa-Datei
  (`__EGL_VENDOR_LIBRARY_FILENAMES`), sobald ein NVIDIA- und ein Mesa-Knoten
  nebeneinander existieren. Dashboard, Editor und Login-Fenster tun das vor
  dem ersten GTK-Aufruf; im Journal steht dann `EGL nur ueber Mesa`.
  `XENEON_EGL_VENDOR=off` schaltet es ab, `=mesa` erzwingt es; ein schon
  gesetztes `__EGL_VENDOR_LIBRARY_FILENAMES` bleibt unangetastet. Rechner mit
  nur einer Art GPU sind nicht betroffen.
- **Monitor-Scale.** Der Xeneon Edge selbst will 1x. In
  `~/.config/hypr/monitors.conf`:
  `monitor = DP-2, 2560x720@60, auto, 1` (die anderen Monitore behalten ihre
  Skalierung).
- **Waybar** liegt per Default auf *jedem* Monitor und frisst ~30px des
  720px-Streifens. In `~/.config/waybar/config.jsonc` `"output"` auf die
  anderen Connectoren begrenzen — oder `SUPER+SHIFT+SPACE`.

### Autostart unter Hyprland

Bleibt der normale XDG-Eintrag in `~/.config/autostart` — kein `exec-once`.
Omarchy startet Hyprland ueber **uwsm**, und uwsm laesst systemd die
`.desktop`-Dateien in `app-*@autostart.service` uebersetzen und mit
`graphical-session.target` starten. Damit bleibt der Schalter *„Start with
der Sitzung starten"* im Editor die einzige Stelle, die den Autostart an-
und abschaltet; ein zusaetzliches `exec-once` wuerde das Dashboard doppelt
starten. Ohne uwsm (Hyprland direkt von der TTY) stattdessen in
`~/.config/hypr/autostart.conf`:

```
exec-once = uwsm-app -- "/pfad/zu/xeneon-edge-dashboard/run.sh"
```

### Fensterregeln

`install-arch.sh` schreibt `~/.config/hypr/xeneon-edge.conf` (bzw. `.lua`, wenn
die Omarchy-Konfiguration bereits auf Lua umgestellt ist) und bindet es in
`~/.config/hypr/autostart.conf` ein. Darin steht nur, was die Omarchy-Defaults
einem Status-Streifen antun wuerden: die globale 0.985-Transparenz, Rahmen,
Rundungen, Abdunkeln im Hintergrund. Auf den Zielmonitor legt sich das
Dashboard selbst (`target_monitor` + `fullscreen_on_target`) — die
`monitor`-Regel steht auskommentiert daneben, falls das mal nicht greift.

Die Lua-Fassung enthaelt zusaetzlich einen Waechter, der den Streifen aus den
Fenster-Dispatchern heraushaelt. `no_focus` reicht dafuer nicht: Omarchys
SUPER+SHIFT+Pfeil ist `swapwindow` und tauscht das aktive Fenster mit dem
naechsten in der Richtung — das Dashboard ist dafuer ein Fenster wie jedes
andere, Fokus oder nicht. Ein Tausch Richtung Streifen kachelte das Dashboard
in den Arbeits-Workspace und liess das getauschte Fenster hinter dem Streifen
zurueck. Hyprland kennt keinen Schalter, der einen Monitor davon ausnimmt;
deshalb hoert das Snippet auf `window.move_to_workspace` / `window.open`
(`hl.on`, Hyprland 0.56+) und raeumt einen Tick spaeter auf: das Dashboard
kommt mit seinem Vollbild-Zustand zurueck auf den Streifen, alles andere, das
dort gelandet ist, zurueck auf den Workspace, von dem es kam. Der Streifen ist
`target_monitor` aus der `settings.json`, ersatzweise der 2560x720-Ausgang.
Die klassische `.conf`-Fassung kann das nicht — ihr fehlt die Event-API.

### Wohin gestartete Fenster gehen

Einstellung *Monitor fuer gestartete Fenster* (`launch_monitor`), im Editor
unter *Einstellungen*. Sie gilt fuer alles, was das Dashboard oeffnet: die
Deck-Eintraege, den Editor selbst und das TradingView-Login.

Ohne sie entscheidet der Compositor, und das heisst in der Praxis: der zuletzt
fokussierte Monitor. Wird das Dashboard per Finger bedient, ist das mitunter
der Streifen selbst — dort liegt das Dashboard im Vollbild davor und es haengt
keine Tastatur, das Fenster ist also gestartet, aber unerreichbar.

Technisch wird vor dem Start der Zielmonitor fokussiert (neue Fenster gehen auf
dem fokussierten Ausgang auf). Es gibt dafuer zwei `hyprctl`-Schreibweisen, und
das Dashboard probiert beide durch:

| Konfiguration | Aufruf |
|---------------|--------|
| klassisch | `hyprctl dispatch focusmonitor DP-4` |
| Lua (Omarchy) | `hyprctl dispatch 'hl.dsp.focus({ monitor = "DP-4" })'` |

Der klassische Aufruf scheitert unter Omarchy, weil dort ein Lua-Parser die
Argumente liest und `DP-4` als Rechnung „DP minus 4" versteht
(`')' expected near 'DP'`). Welche Form geht, entscheidet der erste Aufruf.
Laeuft kein Hyprland, bleibt es beim Standardverhalten — die Einstellung ist
best effort und haelt einen Start nie auf.

### Touchscreen dem Streifen zuordnen

**Der haeufigste Grund dafuer, dass "keine Taste im Dashboard reagiert".**

Ein Touchscreen ohne Ausgangszuordnung wird von Hyprland auf die *Gesamt*flaeche
aller Monitore abgebildet, nicht auf den eigenen. Bei drei Monitoren
(5120 x 2160 gesamt) landet ein Tipp auf den Streifen dann proportional
umgerechnet irgendwo auf dem Hauptmonitor: Workspaces wechseln, Text wird
kopiert, fremde Fenster bekommen Klicks — und das Dashboard bekommt *gar kein*
Ereignis. Es sieht aus wie ein kaputtes Dashboard und ist eine Eingabe, die nie
ankommt.

Pruefen:

```bash
hyprctl getoption input:touchdevice:output   # "[[Auto]]" = nicht zugeordnet
hyprctl devices | sed -n '/Touch Device/,/^$/p'
hyprctl monitors -j | jq -r '.[] | "\(.name) \(.width)x\(.height)"'
```

Zuordnen — Lua-Konfiguration (Omarchy), in `~/.config/hypr/input.lua`:

```lua
hl.device({ name = "wch.cn-touchscreen-1", output = "DP-5" })
hl.device({ name = "wch.cn-touchscreen",   output = "DP-5" })
```

Klassische Konfiguration:

```
device {
    name = wch.cn-touchscreen-1
    output = DP-5
}
```

Geraetenamen kommen aus `hyprctl devices`, der Connector aus `hyprctl monitors`
— beides ist von Rechner zu Rechner verschieden. Zwei Regeln, weil dieselbe
Platte oft zwei Geraete meldet: den Touchscreen und einen absoluten Zeiger
dazu. Zum Testen ohne Reload:

```bash
hyprctl dispatch 'hl.device({ name = "wch.cn-touchscreen-1", output = "DP-5" })'
```

Kommt eine Beruehrung an, laesst sich das ohne Raten nachsehen — das Dashboard
schreibt mit `XENEON_DEBUG_INPUT=1` jeden Druck mit Koordinate und getroffenem
Widget ins Journal:

```bash
XENEON_DEBUG_INPUT=1 ./run.sh
# [input] touch-begin bei (2215,142) Fenster 2560x720 -> Label 'Terminal' button=DeckButton
```

Steht dort nichts, kommt die Beruehrung nicht an und die Ursache liegt im
Compositor, nicht im Dashboard.

### Deck-Vorlage

Die mitgelieferte `config/apps.json` ist KDE-lastig (`konsole`, `dolphin`,
`plasma-systemmonitor`). Fuer Omarchy liegt `config/apps.omarchy.json` daneben
— `xdg-terminal-exec`, `omarchy-launch-browser`, `nautilus`, `omarchy-menu`,
`omarchy-launch-audio`, `hyprctl reload`, `omarchy-toggle-waybar`. Das Skript
kopiert sie nur, wenn `~/.config/xeneon-edge/apps.json` noch nicht existiert.

### Notifications

Omarchy legt seine Toasts auf *jeden* Output (`Variants { model:
Quickshell.screens }`), also auch auf den Streifen — dort direkt ueber den
Deck-Buttons, und weggeklickt bekommt man sie da ohnehin schlecht. Separates
Skript, weil es die Notifications der ganzen Session umbaut und nicht als
stiller Nebeneffekt einer Dashboard-Installation passieren soll:

```bash
./scripts/install-omarchy-notifications.py --only DP-4
```

Es macht zwei Dinge:

- **Toasts vom Dashboard-Monitor fernhalten.** Welcher das ist, kommt aus
  `target_monitor` in `settings.json` (`--monitor` ueberschreibt). Ohne
  `--only` gehen sie auf alle uebrigen Outputs, mit `--only DP-4` fest auf
  diesen einen — dann aber mit Rueckfallebene: haengt DP-4 nicht dran, gehen
  sie auf alles ausser dem Streifen, statt ganz auszubleiben.
- **Ein Schliess-`x` oben rechts auf die Karte.** Das Signal dahinter
  (`closeRequested` -> `dismissPopup`) ist in Omarchy schon verdrahtet, es gab
  nur keinen sichtbaren Knopf — geschlossen wurde per Rechtsklick. Der Knopf
  wird nach `mainColumn` deklariert und liegt damit ueber der kartenweiten
  `MouseArea`; sonst faellt der Klick durch auf `onCardClicked` und loest die
  Default-Aktion der Notification aus, statt sie zu schliessen.

Gearbeitet wird auf einem Klon des Plugins in
`~/.config/omarchy/plugins/<user>.notifications/` (`omarchy plugin clone`), das
Original unter `/usr/share/omarchy` bleibt unangetastet. `--check` zeigt nur,
was passieren wuerde, `--revert` nimmt alles zurueck.

Der Klon friert allerdings den Omarchy-Stand ein, aus dem er geklont wurde —
Bugfixes am Notification-Plugin kommen nicht mehr an. Nach einem groesseren
Omarchy-Update also `--revert` und das Skript neu laufen lassen. Passt dann ein
Anker nicht mehr, bricht es mit genau dieser Stelle ab statt still etwas
Halbes zu hinterlassen.

Nicht geklont werden darf uebrigens `omarchy.bar` — schon der unveraenderte
Klon laesst die Bar auf allen Monitoren verschwinden. `omarchy plugin clone`
traegt fuer `service`- und `bar-widget`-Plugins, fuer das `bar`-Plugin selbst
nicht. Noetig ist es auch nicht: Hyprland ueberspringt `top`-Layer auf einem
Workspace mit Vollbildfenster, die Bar ist auf dem Streifen also unsichtbar.
Nur nach einem `omarchy restart shell` legt sie sich ueber den Header, bis das
Dashboard einmal neu startet.

## Starten

```bash
./run.sh
```

oder

```bash
python3 -m xeneon_edge
```

## Auto-Start einrichten

Entweder über den Editor (Zahnrad → Einstellungen → „Mit der Sitzung starten") oder manuell:

```bash
./scripts/install-autostart.sh
```

## Konfiguration

Alles laeuft ueber den **Editor** (`./scripts/layout-editor.py`, oder das
Zahnrad auf dem Streifen). Er oeffnet sich auf dem Hauptmonitor, weil am
Streifen keine Tastatur haengt, und zeigt den Streifen als Buehne in echter
Proportion: oben die Topbar mit drei Slots, darunter die Spalten. Ein Klick
auf ein Modul, ein Topbar-Widget oder eine Spaltenbreite zeigt rechts die
zugehoerigen Einstellungen — das Formular kommt aus dem `schema` des Moduls.
Es zeigt nur, was im aktuellen Modus etwas bewirkt: die Zeitzonen-Liste der Uhr
erscheint erst bei Darstellung *Zeitzonen*, *Zufaellige Reihenfolge* erst mit
gesetztem Musikordner, und die Widget-Optionen von TradingView verschwinden
ganz, sobald der eigene Chart laeuft. Laengere Bloecke stehen hinter einem
Aufklapper (`group` im Schema), zugeklappt.
Das Launch-Deck erscheint dort als 3×6-Raster: Platz anklicken, Felder
darunter, Plaetze per Ziehen tauschen. *Einstellungen* in der Kopfleiste
zeigt Theme, Zielmonitor, Autostart, Hold-to-confirm, isolierte Starts und
den Speicherdeckel. *Speichern* schreibt `layout.json`, `settings.json` und
`apps.json`; das laufende Dashboard beobachtet alle drei und uebernimmt die
Aenderung sofort. Module, deren Typ und Config gleich bleiben, werden dabei
wiederverwendet — der Chart laedt nicht neu, nur weil eine Spalte breiter
wurde. Beim Ziehen einer Spaltenkante rastet die Breite in **10-px-Schritten**
— der Streifen ist im Editor gut vier Mal kleiner gezeichnet, ein
Bildschirmpixel waeren also mehrere echte, und runde Zahlen kamen nur mit
Glueck heraus; das Zahlenfeld im Inspektor nimmt weiterhin jeden Wert. Liegen
mehrere Module in einer Spalte, laesst sich die Kante zwischen ihnen ziehen
(`height` in Prozent am Modul); die Prozessliste zeigt dann so viele Zeilen,
wie in ihre Hoehe passen. Jedes Deck-Pad hat eine eigene Farbe
(`accent` in `apps.json`, Farbpunkt auf dem Pad im Editor): die untere
Rahmenlinie des Pads auf dem Streifen.

### Module

| Modul | Was es zeigt | Einstellungen |
|-------|--------------|---------------|
| Sensoren | CPU, GPU, RAM, Luefter | welche davon (`metrics`) |
| Prozesse | Top-Prozesse nach CPU | Anzahl Zeilen |
| Audio | Ausgabe/Eingabe, Lautstaerke | — |
| Launch-Deck | 3x6-Raster mit Apps und Macros | im Editor unter *Launch-Deck* |
| Web-Panel | WebKit-View auf eine Adresse | Adresse, Zoom |
| TradingView | Chart-Widget oder eigener Chart | Quelle, Symbol, Intervall, Zeitzone, Indikatoren, Werkzeugleisten |
| OpenMarket | eigener Chart aus einem OpenMarket-Account | Chart-Adresse (traegt *Anmelden / Chart waehlen* ein), Zoom (Standard 72 %) |
| Uhr | Zeit gross | Darstellung, Sekunden, Zeitzonen |
| Kalender | den laufenden Monat | Wochenstart, Kalenderwochen |
| Wiedergabe | was gerade spielt, mit Tasten | Player, Cover an/aus, Musikordner, Zufall |
| Notizen | eine Datei, lesend | Datei |

**Uhr.** Drei Darstellungen: *Zeit und Datum*, *Nur Zeit*, *Zeitzonen*. Die
Ziffern skalieren auf die Flaeche, die das Modul im Layout bekommt — eine
schmale Spalte zeigt sie kleiner, der ganze Streifen macht daraus eine
Wanduhr. Bei *Zeitzonen* steht pro Zeile eine Zone; das Feld nimmt
`Name=Zone`, durch Komma getrennt:

```
London=Europe/London, New York=America/New_York, Tokyo=Asia/Tokyo
```

Die Zonennamen sind die aus `/usr/share/zoneinfo`. Steht kein `=` da, gilt
der Eintrag als Zone und der letzte Pfadteil als Beschriftung
(`America/New_York` → `NEW YORK`). Eine unbekannte Zone wird uebersprungen
und im Journal gemeldet, die uebrigen Zeilen bleiben stehen.

**Kalender.** Der laufende Monat als Raster, heute farbig hervorgehoben,
Tage der Nachbarmonate gedaempft. Bewusst **ohne Termine und ohne Verbindung
nach draussen** — es geht darum, nachzusehen, welcher Wochentag der 23. ist.
Einstellbar ist, ob die Woche am Montag oder Sonntag beginnt und ob die
Kalenderwochen mitlaufen. Die Namen der Wochentage und des Monats folgen der
Spracheinstellung des Systems, wie das Datum im Uhr-Modul.

**Wiedergabe.** Zeigt Titel, Kuenstler, Cover und Fortschritt des gerade
laufenden Players und bietet Zurueck / Play-Pause / Weiter. Das geht ueber
**MPRIS**, die D-Bus-Schnittstelle, die unter Linux praktisch jeder Player
bedient — Spotify, YouTube im Browser, mpv, VLC. Es muss nichts eingerichtet
werden: laeuft ein Player, ist er da.

Das Feld *Player* bleibt normalerweise leer, dann wird der genommen, der
gerade spielt. Traegt man etwas ein (`spotify`, `mpv`, `firefox`), gilt *nur*
dieser — laeuft er nicht, sagt das Modul das auch, statt ersatzweise einen
anderen zu zeigen.

Das Modul richtet sich nach seiner Groesse: Titel, Kuenstler und die Tasten
sind immer da, Cover und Fortschrittsbalken kommen dazu, wenn Platz ist. Bei
einem Live-Stream gibt es keinen Balken — der meldet keine Dauer. Tasten, die
der Player nicht unterstuetzt, sind ausgegraut.

Mit der Maus geht es bequemer ueber die Omarchy-Bar: `omarchy bar put
omarchy.media` legt dasselbe als Bar-Widget auf den Hauptmonitor
(Linksklick Play/Pause, Mitte weiter, Scrollen vor/zurueck, Rechtsklick
Cover-Popup).

**Musikordner: das Modul spielt selbst.** Steht im Feld *Musikordner* ein
Pfad, braucht es gar keinen fremden Player mehr. Der Ordner wird mitsamt
Unterordnern nach Audiodateien durchsucht (`.mp3 .flac .ogg .opus .m4a .aac
.wav .wma` und einige mehr, dazu Video-Container wie `.webm .mp4 .mkv`, von
denen die Tonspur gespielt wird; hoechstens 5000 Stueck), und eine vierte
Taste mit Ordner-Symbol startet ihn — eine eigene Taste, weil Play dem
angezeigten Player gehoert, und mit zwei Browsern auf dem Bus ist fast immer
einer da. Solange der Ordner spielt, leuchtet die Taste; nochmal gedrueckt
stoppt sie ihn, und der fremde Player kommt zurueck. Weiter und Zurueck
blaettern, am Ende der Liste hoert es auf. *Zufaellige Reihenfolge* mischt
einmalig beim Start.

Abgespielt wird ueber eine GStreamer-Pipeline, die nur den Ton dekodiert —
nicht ueber `Gtk.MediaFile`, das bei einem heruntergeladenen Konzert auch das
Bild mitdekodieren wuerde, das nie jemand sieht (gemessen: 70 % eines Kerns
bei einer 4K-AV1-Datei gegen 1 %). Fehlen die Bindings oder Plugins
(`gst-plugins-base`, `gst-plugins-good`; Debian: `gir1.2-gstreamer-1.0`),
sagt das Modul das im Klartext, statt stumm zu bleiben.

Welchen Player das Modul zeigt, entscheidet im Zweifel der Sound-Server:
Brave (Chromium) meldet ueber MPRIS auch mal "Paused" mit eingefrorener
Position, waehrend YouTube hoerbar weiterlaeuft. Sagt kein Player "Playing",
hoert das Modul jeden offenen Ausgabestrom kurz mit (ein stummer Autoplay-Tab
zaehlt also nicht) und zeigt den Player, aus dem Ton kommt, als spielend an —
nur sein Fortschrittsbalken bleibt stehen, die Position kennt allein der
Browser.

Titel und Kuenstler kommen aus dem **Dateinamen** und dem Ordner darueber,
nicht aus den Tags — bei der ueblichen Ablage `Kuenstler/Album/01 Titel.flac`
steht damit das Richtige da. Als Cover wird eine Bilddatei im selben Ordner
genommen (`cover`, `folder`, `front`, `album`, `albumart` als `.jpg`, `.png`
oder `.webp`); ein in die Datei eingebettetes Bild wird *nicht* gelesen.

Beide Quellen teilen sich die drei Tasten. Wer gewinnt: der eigene Player,
solange er laeuft. Pausiert tritt er zurueck, sobald irgendwo sonst etwas
spielt — startet man Spotify, uebernimmt Spotify die Anzeige, ohne dass der
eigene Titel verloren geht.

**Nur Ton, kein Bild.** Das Modul zeigt Cover als Standbild, mehr nicht. Ein
YouTube-Video laeuft im Browser und bleibt dort: MPRIS liefert Metadaten,
kein Bild, und unter Wayland laesst sich das Fenster eines fremden Programms
nicht in den Streifen holen. Wer Bewegtbild auf dem Streifen will, nimmt ein
**Web-Panel** mit der YouTube-Adresse (siehe unten) — das kostet dann aber
einen eigenen WebKit-Prozess.

**Video im Web-Panel.** Ein Web-Panel nimmt jede Adresse, also auch YouTube.
Damit WebKit das Bild dekodiert, braucht es allerdings mehr als
`gst-plugins-good`:

```bash
sudo pacman -S --needed gst-plugins-bad gst-plugins-ugly gst-libav
```

Zu bedenken: jedes Web-Panel kostet einen eigenen WebKit-Prozess, und Video
ist teuer. Der Spotify-Web-Player funktioniert *nicht* — er braucht
Widevine-DRM, das WebKitGTK nicht mitbringt. Fuer Spotify also der
Desktop-Client plus das Wiedergabe-Modul.

**Notizen.** Zeigt eine `.txt`-, `.md`- oder `.json`-Datei und laedt sie neu,
sobald sie sich aendert — geschrieben wird sie woanders, am Rechner mit
Tastatur. JSON wird beim Anzeigen eingerueckt; ist es kaputt, bleibt es roh
stehen. Markdown wird **nicht** formatiert, sondern als Klartext gezeigt.

Bedient wird das Modul mit dem Finger: scrollen durch Wischen, und ein Tipp
auf eine Zeile legt sie in die Zwischenablage — die Zeile leuchtet kurz in
der Akzentfarbe auf. Ohne Tastatur am Streifen ist das der einzige Weg,
etwas aus der Datei herauszubekommen. Angezeigt werden hoechstens 1500
Zeilen; was darueber liegt, meldet die letzte Zeile.

Die Dateien:

- `config/apps.json` — Default-Apps und -Macros (im Repo, dient als Vorlage)
- `~/.config/xeneon-edge/apps.json` — User-Override (der Editor schreibt hierhin)
- `~/.config/xeneon-edge/settings.json` — `auto_start`, `hold_to_confirm`,
  `isolate_launches`, `deck_app_slots`, `target_monitor`, `launch_monitor`,
  `fullscreen_on_target`, `chart_url`, `openmarket_url`, `theme`,
  `web_memory_limit_mb`
- `~/.config/xeneon-edge/layout.json` — Version 3: Profile mit `topbar`
  (Slots `left`/`center`/`right`, je eine Liste `{type, config}`) und
  `columns` (Breite + Module). Topbar-Widgets: `brand`, `status`, `net`,
  `clock`, `weather` (`lat`, `lon`, `label`), `match` (`league`, `team`,
  `short` — ESPN-Codes). Dateien der Versionen 1 und 2 werden beim Laden
  umgebaut: 1 → Topbar-Slots, 2 → TradingView als eigenes Modul.
  Was kein sichtbares Modul braucht, liest der Aggregator auch nicht: ohne
  Prozess-Modul kein psutil-Durchlauf, ohne Wetter-Widget kein Open-Meteo.

### Farbthemes

`theme` in `settings.json` bzw. Editor → Einstellungen → *Farbthema*; der
Wechsel wirkt sofort, ohne Neustart. Mitgeliefert in `xeneon_edge/themes/`:

| `theme`   | Look                                              |
|-----------|---------------------------------------------------|
| `crimson` | Rot auf Schwarz (Default, der bisherige Look)     |
| `ember`   | Orange auf Schwarz                                |
| `ice`     | Cyan auf Schwarz                                  |
| `matrix`  | Gruen auf Schwarz                                 |
| `nord`    | Grau-Blau, kein reines Schwarz                    |
| `omarchy` | folgt der aktiven Omarchy-Palette (siehe unten)   |

Ein eigenes Theme ist eine weitere `.toml` in diesem Ordner — `crimson.toml`
kopieren, die 13 Farben aendern, fertig; der Dateiname ist der Wert fuer
`theme`. `style.css` enthaelt keine Farbwerte mehr, nur Namen (`@accent`,
`@bg`, …), die `theme.py` aus der Palette davor definiert. Das anonyme
TradingView-Widget bekommt Hintergrund und Grid aus derselben Palette; die
volle Chart-Seite mit Account bringt ihr eigenes Theme mit.

`omarchy` liest `~/.local/state/omarchy/current/theme/colors.toml` und
beobachtet das Verzeichnis: `omarchy-theme-set` faerbt das Dashboard mit um.
Der Eintrag erscheint nur, wenn diese Datei existiert — auf Fedora/KDE fehlt
er. Die Zuordnung (Omarchy-`accent` → Akzent, `red` → heiss, `yellow` → warm,
drei Hintergrundstufen → Fenster/Panel/Buttons) steht in `theme.py`.

### Deck-Aufteilung

Das Deck hat fest 18 Plätze (3 Spalten × 6 Zeilen, `DECK_*` in
`config_store.py` — die Buttonhöhe ist auf die 660px Inhaltsfläche des Xeneon
Edge abgestimmt). `deck_app_slots` (Editor → Launch-Deck → *Plaetze fuer
Apps*, 0–18) legt fest, wie viele davon an Apps gehen; der Rest geht an
Macros:

| `deck_app_slots` | Deck                                     |
|------------------|------------------------------------------|
| `0`              | alle 18 Buttons sind Macros              |
| `9` (Default)    | Zeile 1–3 Apps, Zeile 4–6 Macros         |
| `18`             | alle 18 Buttons sind Apps                |

Gefüllt wird slotweise, nicht zeilenweise: bei `4` teilen sich Apps und Macros
die zweite Zeile. Die Apps-/Macros-Tabs zeigen jeweils exakt so viele Slots,
wie das Deck von dieser Kategorie auch rendert — was dort steht, landet auch
auf dem Display.

Einträge, die über das aktuelle Kontingent hinausgehen, bleiben in `apps.json`
erhalten: den Regler runter- und wieder hochdrehen bringt sie unverändert
zurück.

Ein Slot mit Kommando, aber ohne Label, beschriftet sich selbst mit dem
Dateinamen des Kommandos (`display_label()` in `ui/deck.py`). Vorher sah so ein
Slot leer aus, löste beim Antippen aber trotzdem aus.

Beschriftungen brechen auf zwei Zeilen um (11px, minimale Sperrung). Gemessen
mit Pango bei der realen Buttonbreite passt damit alles bis
`g1_gemma-4-e4b_128k` vollständig auf den Button; vorher wurde schon
„qwen 96k vision" gekürzt.

### TradingView

TradingView ist ein **eigenes Modul**, getrennt vom Web-Panel. Das Web-Panel
fragt nur nach einer Adresse; TradingView fragt, *wie* — Feld *Quelle*:

| Quelle (`mode`)      | Was laeuft                                       |
|----------------------|--------------------------------------------------|
| `widget` (Default)   | *Advanced Chart*-Widget, anonym, konfigurierbar   |
| `account`            | die echte Chart-Seite mit deinem gespeicherten Layout, aus `url` |

Bis Layout-Version 2 war beides ein Web-Panel: leere Adresse hiess „Widget",
eine `tradingview.com`-Adresse hiess „eigener Chart". Bestehende Layouts
werden beim Laden umgestellt, es ist nichts von Hand zu tun.

**Das Widget einstellen.** Im Editor hinter dem Aufklapper
*Widget-Einstellungen* — bei Quelle *Eigener Chart* ist der Block gar nicht da,
dort gilt ohnehin das Layout aus dem Account. Symbol (`BINANCE:BTCUSDT`,
`NASDAQ:AAPL`, `SIX:NESN` …), Intervall, Zeitzone, Werkzeugleisten an/aus und
die Indikatoren zum Anklicken:

| Anzeige | Kennung |
|---------|---------|
| Volumen | eigene Widget-Option (`hide_volume`), zaehlt nicht ins Limit |
| RSI | `STD;RSI` |
| MACD | `STD;MACD` |
| Bollinger-Baender | `STD;Bollinger_Bands` |
| EMA / SMA | `STD;EMA`, `STD;SMA` |
| VWAP | `STD;VWAP` |
| Stochastic RSI | `STD;Stochastic_RSI` |
| Ichimoku-Wolke | `STD;Ichimoku%1Cloud` |
| Supertrend | `STD;Supertrend` |
| RSI-Divergenz | `STD;Divergence%1Indicator` |

Zwei Dinge, die man nur durch Nachmessen erfaehrt — das Widget meldet
naemlich **keinen Fehler**, es laesst den Indikator einfach weg:

- **Hoechstens fuenf Indikatoren.** Alles darueber wird stillschweigend
  verworfen, und zwar die *letzten* der Liste. Das Modul kappt deshalb selbst
  bei fuenf (`TV_MAX_STUDIES` in `ui/chart.py`).
- **Die Liste ist die vollstaendige.** ATR, OBV, ADX, MFI und Awesome
  Oscillator wurden in mehreren Schreibweisen probiert und von keiner
  erkannt; sie stehen deshalb nicht zur Auswahl, statt einen Haken
  anzubieten, der nichts bewirkt. Wer sie braucht, nimmt den eigenen Chart —
  der bringt die Indikatoren aus dem Account mit.

Das eingebettete Widget kann gespeicherte Layouts **nicht** laden — es ist
account-los und nimmt nur die Parameter oben. Wer seine Zeichnungen und
Templates sehen will, muss die richtige Seite laden und dort angemeldet sein.

Angemeldet wird ueber den Editor: TradingView-Modul anklicken → **Anmelden /
Chart waehlen**. Der Button startet dasselbe Skript auch von Hand:

```bash
./scripts/tradingview-login.py
```

Das oeffnet dieselbe Browser-Session in einem normalen 1400x900-Fenster auf dem
Hauptmonitor — am 2560x720-Streifen haengt ueblicherweise keine Tastatur.

Von allein landet es dort nicht: Hyprland legt neue Fenster auf den
fokussierten Workspace, und der ist genau dann der Streifen, wenn das Login per
Touch aus dem Dashboard heraus gestartet wurde. Dann ging es hinter dem
Vollbild-Dashboard auf und war weder sichtbar noch bedienbar. Deshalb sucht
sich das Fenster seinen Monitor selbst (`find_login_monitor` in
`ui/monitors.py`, groesster Ausgang ausser `target_monitor`). GTK4 kann ein
Fenster auf Wayland nicht positionieren — `fullscreen_on_monitor()` ist die
einzige API, die ueberhaupt einen Monitor annimmt. Also einmal dort Vollbild
anmelden und im naechsten Frame wieder verlassen; der Compositor hat das
Fenster dann schon auf dem richtigen Ausgang. Dass es dort schwebt statt zu
kacheln, macht die Regel aus `install-arch.sh`. Dort
anmelden, den gewuenschten gespeicherten Chart oeffnen, *Als Chart uebernehmen*
druecken: das schreibt die aktuelle URL nach `chart_url` und beendet das
Fenster. Login ueber Google/Apple oeffnet ein Popup — das Skript faengt es ab
und zeigt es in einem eigenen Fenster (ohne diesen Handler passiert beim Klick
gar nichts).

Das Profil liegt in `~/.local/share/xeneon-edge/webkit/` (Cookies als
`cookies.sqlite`, dazu LocalStorage). Persistent ist es nur, weil die
`NetworkSession` explizit mit diesem Verzeichnis gebaut wird — eine
Default-`WebKit.WebView()` haelt ihren Cookie-Jar im Speicher, der Login waere
nach jedem Neustart weg.

Zu beachten:

- **Kein Neustart noetig.** Der Editor wartet auf das Ende des Login-Fensters,
  traegt die URL ins Feld *Chart-Adresse* ein und stellt *Quelle* auf
  „Eigener Chart"; nach *Speichern* haengt sich das Panel im laufenden
  Dashboard um. Der Button *Zurueck zum Widget* daneben stellt die Quelle
  wieder um und laesst die Adresse stehen. Die Adresse laesst sich auch von
  Hand eintippen — der Editor laeuft ja auf dem Monitor mit Tastatur.
- **Der erste Aufbau dauert.** Das Panel bleibt einige Sekunden leer, bis
  Layout und Indikatoren geladen sind — beim anonymen Widget steht der Chart
  fast sofort. Das ist kein Fehler, sondern der Preis des eigenen Layouts.
- **Telemetrie-Requests scheitern** (`telemetry.tradingview.com`, `TypeError:
  Load failed`), wenn ein Adblocker oder DNS-Filter aktiv ist. Ohne Folgen —
  der Chart laedt vollstaendig.
- **Die volle Seite kostet mehr** als das Widget — eigener Web-Prozess, mehr
  RAM, mehr CPU. Bei einem Panel, das durchlaeuft, merkbar: frisch geladen
  rund 1 GB RSS und 5 % eines Kerns, und die Seite waechst ueber Stunden
  (3,7 GB Spitze der Dashboard-Unit gemessen). Deshalb haengt am Web-Prozess
  ein Deckel, `web_memory_limit_mb` in `settings.json` (Default 1536, 0 =
  aus, gemessen als RSS des Web-Prozesses): ab 70 % gibt WebKit Caches
  frei, am Limit beendet es den
  Web-Prozess, und das Panel laedt die Seite drei Sekunden spaeter neu —
  sichtbar als kurz leeres Panel, im Journal als „Web-Prozess des Charts
  beendet (exceeded-memory-limit)“. Dasselbe passiert nach einem Absturz des
  Web-Prozesses; vorher blieb das Panel dann bis zum Neustart leer.
- **Die Session kann ablaufen.** Dann steht im Panel die Login-Wand statt eines
  Charts; im Editor beim TradingView-Modul erneut *Anmelden / Chart waehlen*.
- **Das Login-Fenster hat keinen Speicherdeckel.** Der Google-Login oeffnet
  ein Popup im selben Web-Prozess, zusammen lagen die beiden bei 1,6 GB —
  mit dem Deckel des Chart-Panels wurde der Prozess nach 30 s gekillt und
  das Fenster nahm keine Eingabe mehr an. Ein zweiter Start holt das
  vorhandene Fenster nach vorn statt ein zweites darueberzulegen.
- Automatisiertes Einloggen waere gegen die TradingView-ToS — deshalb ein
  Fenster zum Selbst-Anmelden und kein Skript, das Zugangsdaten eintippt.

### OpenMarket

OpenMarket ([openmarket.xyz](https://openmarket.xyz)) ist die zweite
Chart-Quelle, ein **eigenes Modul** neben TradingView. Ein anonymes Widget
gibt es nicht: das Modul zeigt immer den eigenen Chart aus dem Account, aus
der Adresse in *Chart-Adresse* (`url`, Form
`https://openmarket.xyz/chart/<id>`). Wer gar keinen Chart will, entfernt
das Modul im Editor — in die mittlere Spalte passt jedes andere Modul, oder
keines.

Angemeldet wird wie bei TradingView: im Editor das OpenMarket-Modul
anklicken → **Anmelden / Chart waehlen**. Dasselbe Skript, mit der Seite als
Argument:

```bash
./scripts/tradingview-login.py --site openmarket
```

Anmelden, Chart oeffnen, *Als Chart uebernehmen* — das schreibt die Adresse
nach `openmarket_url` in `settings.json`, der Editor traegt sie ins Modul
ein. Beide Seiten teilen sich ein WebKit-Profil, eine TradingView- und eine
OpenMarket-Session leben also nebeneinander.

Die Seite ist fuer einen breiten Desktop-Browser gebaut; in der Mittelspalte
des Streifens (rund 1270 px) schnitt sie das Orderbuch rechts ab. Das Modul
setzt deshalb standardmaessig einen Seitenzoom von **72 %** (*Zoom* im
Editor, 50 bis 150), womit die Seite rund 1760 CSS-Pixel sieht — bei 80 %
fehlte noch die Total-Spalte des Orderbuchs; das Web-Panel hat dasselbe Feld
mit Standard 100.

Gemessen am Streifen ueber sechs Stunden (16.10.2026, Fedora, AMD-GPU): die
OpenMarket-Seite liegt bei rund 1 GB RSS und haelt dauerhaft **etwa ein
Drittel eines Kerns** beschaeftigt — um die 30 % —, wo der eigene
TradingView-Chart etwa 5 % braucht. Der Speicher blieb flach, die Seite hat
nie neu geladen. Die CPU-Last ist das eine, was man vor der Wahl abwaegen
sollte; der Speicherdeckel (*Speicherdeckel Web-Panel* in den Einstellungen)
gilt fuer sie wie fuer jede Web-View.

### Icons

Das Feld `icon` eines Eintrags akzeptiert drei Formen, in dieser Reihenfolge:

1. **Mitgeliefertes Icon** aus `xeneon_edge/icons/` per Name — Endung und
   `-symbolic` optional, `llm-start` findet `llm-start-symbolic.svg`
2. **absoluter Dateipfad** zu einem SVG/PNG
3. **Name aus dem Icon-Theme** (`utilities-terminal`, `system-run-symbolic`, …)

Mitgeliefert sind drei zusammengehörige Chip-Symbole für lokale LLM-Server:

| Name          | Symbol           | gedacht für            |
|---------------|------------------|------------------------|
| `llm-start`   | Chip mit ▶       | Modellserver starten   |
| `llm-vision`  | Chip mit Auge    | multimodales Modell    |
| `llm-stop`    | Chip mit ■       | Server stoppen         |

Ohne `icon`-Feld greift die Automatik: Macro-ID-Schlüsselwort (`shutdown`,
`lock`, …) → passende `.desktop`-Datei → Theme-Name → Kategorie-Fallback.
Theme-Namen werden vor der Rückgabe mit `has_icon()` geprüft — sonst landete
jedes Shell-Script bei Schritt „Kommandoname als Icon-Name" und alle
Script-Macros zeigten dasselbe „kein Eintrag"-Symbol.

### Wie Deck-Einträge gestartet werden

Default (`isolate_launches: true`) ist `systemd-run --user`: jeder Eintrag
bekommt eine eigene transiente Unit `xeneon-deck-<slot>-<id>.service` (z.B.
`xeneon-deck-02-macro2`) und damit eine eigene cgroup unter `app.slice`. Die
Slotnummer steht mit drin, weil `id` nicht eindeutig ist — beim Umsortieren
wandern die Einträge, ihre `id` bleibt stehen.

Das ist kein Kosmetik-Detail. Per `subprocess.Popen` gestartet bliebe der
Prozess Kind des Dashboards und liefe in *dessen* Unit — bei einem lokalen
llama.cpp-Server mit `--threads 16` heißt das: CPU-Weight und Memory-Reclaim
teilen sich UI und Modell, das Dashboard ruckelt beim Laden und während der
Inferenz. Dazu käme, dass ein `systemctl --user restart` des Dashboards den
Modellserver mitreißt (`KillMode=control-group`) und dass Stop-Skripte, die die
Unit aus `/proc/PID/cgroup` ableiten, die Dashboard-Unit erwischen.

Praktische Folgen:

```bash
systemctl --user list-units 'xeneon-deck-*'        # was läuft gerade?
systemctl --user stop     xeneon-deck-02-macro2    # sauber beenden
journalctl --user -u      xeneon-deck-02-macro2 -f # Ausgabe des Scripts
```

Ein zweiter Klick auf einen bereits laufenden Eintrag startet keine zweite
Instanz, sondern scheitert an „unit already exists“ — die Meldung landet im
Journal der Dashboard-Unit (`journalctl --user -u xeneon-edge`).

Einzelne Einträge lassen sich mit `"launch": "direct"` in `apps.json` davon
ausnehmen; der Schalter im Editor (Einstellungen) stellt global auf das alte
Popen-Verhalten zurück.

## Tastatur / Bedienung

- Zahnrad-Button: oeffnet den Editor auf dem Hauptmonitor (siehe unten) —
  Layout, Modul-Einstellungen, Deck und alle Settings an einem Ort
- `FS`: Vollbild umschalten
- `X`: Beenden
- Macros mit `confirm: true`: Button gedrückt halten (1 s) bis er rot aufleuchtet
- `×` in einer Prozess-Zeile: ~0,8 s halten (Button füllt sich rot) → SIGTERM.
  Kurzer Klick macht nichts; während des Haltens friert die Liste ein, damit
  kein Reorder den falschen Prozess unter den Cursor schiebt.

## Was unter der Haube läuft

| Bereich   | Quelle                                                                     |
|-----------|-----------------------------------------------------------------------------|
| CPU-Last  | `/proc/stat`                                                                |
| CPU-Takt  | `/proc/cpuinfo`                                                             |
| CPU-Temp  | `/sys/class/hwmon/*` (k10temp/coretemp)                                     |
| RAM       | `/proc/meminfo`                                                             |
| Netzwerk  | `/proc/net/dev`                                                             |
| Lüfter    | `/sys/class/hwmon/*/fan*_input`                                             |
| AMD-GPU   | `/sys/class/drm/cardX/device/{gpu_busy_percent,mem_info_vram_*}` + hwmon    |
| NVIDIA    | NVML (`pynvml`), Fallback `nvidia-smi --query-gpu=...`                      |
| Audio     | `pactl get/set-sink-volume`, `set-default-sink`, `wpctl`; neu gelesen nur bei Ereignis aus `pactl subscribe` |

Keine Admin-Rechte nötig.

## Bekannte Einschränkungen

- AMD-GPU-Name wird aus `modalias` abgeleitet — generisch („AMD GPU (Radeon)"). Für den schöneren Namen müsste man `lspci` oder `pciutils` parsen.
- Ohne `pynvml` (Arch `python-nvidia-ml-py`, Debian `python3-pynvml`) kommen die NVIDIA-Werte aus `nvidia-smi`, ein Prozessstart pro Tick (~28 ms). Mit NVML sind es 0,1 ms; die Statuspille zeigt nicht, welcher Weg läuft, `verify-install.py` schon.
- Läuft `pactl subscribe` nicht (kein Server), wird Audio wie früher alle 2 s gepollt; sonst nur bei Änderung und alle 30 s zur Sicherheit.

## Verzeichnisstruktur

```
xeneon-edge-dashboard/
  run.sh
  requirements.txt
  config/apps.json
  config/apps.omarchy.json
  scripts/install-autostart.sh
  scripts/install-debian.sh    # Debian-13-Setup: Pakete, Verify, Settings, Autostart
  scripts/install-arch.sh      # Arch/Omarchy-Setup: + Deck-Vorlage, Hyprland-Regeln
  scripts/verify-install.py    # Abhaengigkeits-Check, von beiden Installern benutzt
  scripts/tradingview-login.py # Einmal-Login fuer die Chart-Module (TradingView, --site openmarket)
  xeneon_edge/
    app.py             # Adw.Application + CSS + Aggregator-Wiring
    config_store.py    # settings.json + apps.json + autostart .desktop
    paths.py
    style.css          # GTK4-Stylesheet, farbfrei — Farben kommen aus theme.py
    theme.py           # Paletten laden (themes/*.toml, Omarchy), @define-color erzeugen
    themes/            # crimson, ember, ice, matrix, nord
    layout_store.py    # layout.json: Spalten, Module, Breiten
    modules/           # Modul-Register + mitgelieferte Module
    sensors/           # CPU/GPU/RAM/Net/Fans/Audio/Weather/Aggregator
    ui/                # Window + Panels + Deck + AudioPanel + Chart + Settings
      layout.py        # FixedWidth — harte Spaltenbreiten (Werte dürfen nicht schieben)
```
