# Xeneon Edge Dashboard — Linux/GTK4

Linux-Port des Windows-Desktop-Dashboards — native GTK4-Oberfläche, Sensoren direkt aus `/proc` und `/sys`, kein .NET, kein WPF.

## Features

- CPU: Last, Temperatur, Takt
- GPU: AMD (über `/sys/class/drm`) **und** NVIDIA (über `nvidia-smi`) gleichzeitig
- RAM, Netzwerk, Lüfter (alle hwmon-Sensoren)
- Top-Prozesse (psutil) — `×` gedrückt halten beendet den Prozess (SIGTERM)
- Audio: PipeWire-Lautstärke + Mute + Default-Device-Auswahl (`pactl` / `wpctl`)
- Wetter (open-meteo, Wohlen CH)
- TradingView-Chart (WebKitGTK) — wahlweise das anonyme Widget oder die
  echte Chart-Seite mit dem eigenen Account und gespeichertem Layout
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
                 gstreamer1.0-plugins-good
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
- **Der Repo-Pfad enthält ein Leerzeichen** (`Monitor dashboard`). Beim
  Kopieren auf den anderen Rechner Anführungszeichen nicht vergessen; der
  Autostart-Eintrag quotet `Exec=` bereits korrekt.
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
exec-once = uwsm-app -- "/pfad/zu/linux/run.sh"
```

### Fensterregeln

`install-arch.sh` schreibt `~/.config/hypr/xeneon-edge.conf` (bzw. `.lua`, wenn
die Omarchy-Konfiguration bereits auf Lua umgestellt ist) und bindet es in
`~/.config/hypr/autostart.conf` ein. Darin steht nur, was die Omarchy-Defaults
einem Status-Streifen antun wuerden: die globale 0.985-Transparenz, Rahmen,
Rundungen, Abdunkeln im Hintergrund. Auf den Zielmonitor legt sich das
Dashboard selbst (`target_monitor` + `fullscreen_on_monitor`) — die
`monitor`-Regel steht auskommentiert daneben, falls das mal nicht greift.

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
Das Launch-Deck erscheint dort als 3×6-Raster: Platz anklicken, Felder
darunter, Plaetze per Ziehen tauschen. *Einstellungen* in der Kopfleiste
zeigt Theme, Zielmonitor, Autostart, Hold-to-confirm, isolierte Starts und
den Speicherdeckel. *Speichern* schreibt `layout.json`, `settings.json` und
`apps.json`; das laufende Dashboard beobachtet alle drei und uebernimmt die
Aenderung sofort. Module, deren Typ und Config gleich bleiben, werden dabei
wiederverwendet — der Chart laedt nicht neu, nur weil eine Spalte breiter
wurde. Liegen mehrere Module in einer Spalte, laesst sich die Kante zwischen
ihnen ziehen (`height` in Prozent am Modul); die Prozessliste zeigt dann so
viele Zeilen, wie in ihre Hoehe passen. Jedes Deck-Pad hat eine eigene Farbe
(`accent` in `apps.json`, Farbpunkt auf dem Pad im Editor): die untere
Rahmenlinie des Pads auf dem Streifen.

Die Dateien:

- `config/apps.json` — Default-Apps und -Macros (im Repo, dient als Vorlage)
- `~/.config/xeneon-edge/apps.json` — User-Override (der Editor schreibt hierhin)
- `~/.config/xeneon-edge/settings.json` — `auto_start`, `hold_to_confirm`,
  `isolate_launches`, `deck_app_slots`, `target_monitor`, `fullscreen_on_target`,
  `chart_url`, `theme`, `web_memory_limit_mb`
- `~/.config/xeneon-edge/layout.json` — Version 2: Profile mit `topbar`
  (Slots `left`/`center`/`right`, je eine Liste `{type, config}`) und
  `columns` (Breite + Module). Topbar-Widgets: `brand`, `status`, `net`,
  `clock`, `weather` (`lat`, `lon`, `label`), `match` (`league`, `team`,
  `short` — ESPN-Codes). Eine Version-1-Datei wird beim Laden umgebaut.
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

### TradingView mit eigenem Account

Das Web-Panel kennt zwei Betriebsarten, umgeschaltet ueber `url` in seiner
Modul-Config (`layout.json`, im Editor das Feld *Adresse*):

| `url`                                             | Was laeuft                                     |
|---------------------------------------------------|------------------------------------------------|
| `""` (Default)                                    | *Advanced Chart*-Widget, anonym, BTC/USDT       |
| `https://www.tradingview.com/chart/AbCdEf12/`     | die echte Chart-Seite mit deinem Layout         |

Das eingebettete Widget kann gespeicherte Layouts **nicht** laden — es ist
account-los und nimmt nur Parameter (Symbol, Intervall, `studies`). Wer seine
Indikatoren, Zeichnungen und Templates sehen will, muss die richtige Seite
laden und dort angemeldet sein.

Angemeldet wird ueber den Editor: Web-Panel anklicken → **Anmelden / Chart
waehlen**. Der Button startet dasselbe Skript auch von Hand:

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

- **Kein Neustart noetig.** Der Editor wartet auf das Ende des Login-Fensters
  und traegt die URL ins Feld *Adresse* des Web-Panels ein; nach *Speichern*
  haengt sich das Panel im laufenden Dashboard um. Der Button *Widget*
  daneben leert die Adresse und schaltet zurueck auf das anonyme
  BTC/USDT-Widget. Die Adresse laesst sich auch von Hand eintippen — der
  Editor laeuft ja auf dem Monitor mit Tastatur.
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
  Charts; im Editor beim Web-Panel erneut *Anmelden / Chart waehlen*.
- **Das Login-Fenster hat keinen Speicherdeckel.** Der Google-Login oeffnet
  ein Popup im selben Web-Prozess, zusammen lagen die beiden bei 1,6 GB —
  mit dem Deckel des Chart-Panels wurde der Prozess nach 30 s gekillt und
  das Fenster nahm keine Eingabe mehr an. Ein zweiter Start holt das
  vorhandene Fenster nach vorn statt ein zweites darueberzulegen.
- Automatisiertes Einloggen waere gegen die TradingView-ToS — deshalb ein
  Fenster zum Selbst-Anmelden und kein Skript, das Zugangsdaten eintippt.

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

Keine Admin-Rechte nötig (im Gegensatz zur Windows-Version).

## Bekannte Einschränkungen

- AMD-GPU-Name wird aus `modalias` abgeleitet — generisch („AMD GPU (Radeon)"). Für den schöneren Namen müsste man `lspci` oder `pciutils` parsen.
- Ohne `pynvml` (Arch `python-nvidia-ml-py`, Debian `python3-pynvml`) kommen die NVIDIA-Werte aus `nvidia-smi`, ein Prozessstart pro Tick (~28 ms). Mit NVML sind es 0,1 ms; die Statuspille zeigt nicht, welcher Weg läuft, `verify-install.py` schon.
- Läuft `pactl subscribe` nicht (kein Server), wird Audio wie früher alle 2 s gepollt; sonst nur bei Änderung und alle 30 s zur Sicherheit.

## Verzeichnisstruktur

```
linux/
  run.sh
  requirements.txt
  config/apps.json
  config/apps.omarchy.json
  scripts/install-autostart.sh
  scripts/install-debian.sh    # Debian-13-Setup: Pakete, Verify, Settings, Autostart
  scripts/install-arch.sh      # Arch/Omarchy-Setup: + Deck-Vorlage, Hyprland-Regeln
  scripts/verify-install.py    # Abhaengigkeits-Check, von beiden Installern benutzt
  scripts/tradingview-login.py # Einmal-Login fuer das Chart-Panel (eigene Session)
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
