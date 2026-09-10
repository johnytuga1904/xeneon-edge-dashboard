"""Wiedergabe: was gerade laeuft, mit Tasten dazu.

Haengt an MPRIS (siehe sensors/mpris.py) und bedient damit jeden Player, der
sich an den Standard haelt — Spotify, YouTube im Browser, mpv, VLC.

Zusaetzlich kann das Modul selbst spielen: ist in den Einstellungen ein
Musikordner gesetzt, wird er zur Playlist (siehe ui/localplayer.py). Beide
Quellen teilen sich dieselben drei Tasten. Wer gewinnt, entscheidet
``_pick_source``: der eigene Player, solange er laeuft; pausiert tritt er
zurueck, sobald sonst etwas spielt. So uebernimmt Spotify die Anzeige, ohne
dass die eigene Wiedergabe verloren geht.

Das Modul richtet sich nach seiner Groesse. Titel, Kuenstler und die Tasten
sind immer da; Cover und Fortschrittsbalken kommen dazu, wenn Platz ist, und
verschwinden wieder, wenn das Modul im Layout schmal oder flach gezogen wird.
Die Schwellen zum Ein- und Ausblenden liegen bewusst auseinander: mit einer
einzigen Schwelle wuerde ein Modul, das genau darauf liegt, bei jedem
Durchlauf umschalten und flackern.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio  # noqa: E402

from ..sensors.mpris import MprisWatcher, Track
from .localplayer import LocalPlayer

# Ein- und Ausblendschwellen (Breite x Hoehe des Moduls, in Pixeln). Zwischen
# den Paaren liegt die Hysterese.
COVER_ON = (250, 150)
COVER_OFF = (230, 130)
PROGRESS_ON_H = 100
PROGRESS_OFF_H = 90
HEADER_ON_H = 120
HEADER_OFF_H = 105

# Aenderungen sammeln, statt bei jedem PropertiesChanged neu zu lesen: manche
# Player schicken im Sekundentakt.
REFRESH_DELAY_MS = 150

# Cover werden klein gehalten — es sind Albumbilder, keine Galerie.
ART_CACHE_MAX = 4


class MediaPlayerModule(Gtk.Box):
    __gtype_name__ = "XeMediaPlayerModule"

    def __init__(self, config: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("panel")
        self.add_css_class("media-module")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.needs = frozenset()

        self._show_cover = config.get("show_cover", True) is not False
        self._track = Track()
        self._use_local = False
        self._art_cache: dict[str, Gdk.Texture] = {}
        self._art_url = ""
        self._refresh_source = 0
        self._cover_side = 0
        self._last_size = (0, 0)
        # Zustand der Hysterese: was gerade sichtbar ist.
        self._vis = {"cover": False, "progress": False, "header": True}

        # Kopf
        self._header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._header.add_css_class("panel-header")
        label = Gtk.Label(label="Wiedergabe", xalign=0)
        label.add_css_class("panel-label")
        self._player_label = Gtk.Label(label="", xalign=1)
        self._player_label.add_css_class("panel-sublabel")
        self._player_label.set_hexpand(True)
        self._player_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        self._header.append(label)
        self._header.append(self._player_label)
        self.append(self._header)

        # Koerper: Cover links, Text und Tasten rechts
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        body.set_vexpand(True)
        self.append(body)

        # Quadratische Kachel, egal was der Player liefert: Spotify schickt
        # quadratische Cover, YouTube 16:9-Vorschaubilder. ContentFit.COVER
        # beschneidet auf das Quadrat, statt Balken stehen zu lassen — sonst
        # haette das Modul je nach Player eine andere Breite.
        self._cover = Gtk.Picture()
        self._cover.set_content_fit(Gtk.ContentFit.COVER)
        self._cover.add_css_class("media-cover")
        self._cover.set_valign(Gtk.Align.CENTER)
        self._cover.set_halign(Gtk.Align.START)
        self._cover.set_hexpand(False)
        self._cover.set_can_shrink(True)
        body.append(self._cover)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        right.set_hexpand(True)
        right.set_valign(Gtk.Align.CENTER)
        body.append(right)

        # Zentriert, nicht linksbuendig: der Streifen wird im Vorbeigehen
        # angeschaut, und eine Mitte findet das Auge schneller als eine Kante.
        self._title = Gtk.Label(label="", xalign=0.5)
        self._title.add_css_class("media-title")
        self._title.set_ellipsize(3)
        self._title.set_hexpand(True)
        self._artist = Gtk.Label(label="", xalign=0.5)
        self._artist.add_css_class("media-artist")
        self._artist.set_ellipsize(3)
        right.append(self._title)
        right.append(self._artist)

        self._progress = Gtk.ProgressBar()
        self._progress.add_css_class("media-progress")
        right.append(self._progress)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.add_css_class("media-buttons")
        buttons.set_halign(Gtk.Align.CENTER)
        self._prev = self._button("media-skip-backward-symbolic", "Previous")
        self._play = self._button("media-playback-start-symbolic", "PlayPause")
        self._next = self._button("media-skip-forward-symbolic", "Next")
        for b in (self._prev, self._play, self._next):
            buttons.append(b)
        right.append(buttons)

        # Beim Einblenden steht die Groesse fest; ohne das waere das Modul
        # bis zum ersten Tick eine Sekunde lang falsch aufgeteilt.
        self.connect("map", lambda *_a: GLib.idle_add(self._check_size))

        self._watcher = MprisWatcher(str(config.get("player") or ""), self._on_change)
        self._watcher.start()

        folder = str(config.get("music_dir") or "").strip()
        self._local = LocalPlayer(folder, bool(config.get("shuffle")),
                                  self._on_change) if folder else None

        self._refresh()

    def _button(self, icon: str, method: str) -> Gtk.Button:
        """Symbolisches Icon statt eines Unicode-Zeichens.

        "⏮" und "⏭" landen bei der Emoji-Schrift und kommen bunt heraus —
        neben einer monochromen Oberflaeche sieht das aus wie ein Versehen.
        Symbolische Icons nehmen die Textfarbe an und folgen damit dem Theme.
        """
        button = Gtk.Button.new_from_icon_name(icon)
        button.add_css_class("media-btn")
        button.connect("clicked", self._on_button, method)
        return button

    # ----- Daten -----

    def _on_change(self) -> None:
        if self._refresh_source:
            return
        self._refresh_source = GLib.timeout_add(REFRESH_DELAY_MS, self._refresh_now)

    def _refresh_now(self) -> bool:
        self._refresh_source = 0
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _on_button(self, _button, method: str) -> None:
        local = self._local
        if self._use_local and local is not None:
            {"PlayPause": local.play_pause,
             "Next": local.next,
             "Previous": local.previous}[method]()
            return
        if not self._track.present:
            # Nichts laeuft, aber ein Ordner ist eingestellt: Play startet ihn.
            if local is not None and method == "PlayPause":
                local.play_pause()
            return
        self._watcher.call(self._track.player, method)
        # Nicht auf PropertiesChanged warten: eine Taste, die erst nach einer
        # Zehntelsekunde reagiert, fuehlt sich kaputt an.
        self._on_change()

    def _pick_source(self) -> bool:
        """True = der eigene Ordner-Player liefert die Anzeige.

        Laufend hat er Vorrang — er wurde ja an diesem Modul gestartet.
        Pausiert tritt er zurueck, sobald irgendwo sonst etwas spielt, sonst
        wuerde ein vergessener pausierter Titel Spotify verdecken.
        """
        local = self._local
        if local is None or not local.active:
            return False
        return local.playing or not self._track.playing

    def _refresh(self) -> None:
        self._track = self._watcher.read()
        self._use_local = self._pick_source()

        if self._use_local:
            self._show_local()
        elif self._track.present:
            self._show_track()
        else:
            self._show_idle()

        self._update_progress()
        self._apply_visibility()

    def _show_local(self) -> None:
        local = self._local
        assert local is not None
        self._title.remove_css_class("media-idle")
        self._player_label.set_label(local.label)
        self._title.set_label(local.title or "—")
        self._artist.set_label(local.artist)
        self._load_art(local.art_url)
        self._play.set_icon_name("media-playback-pause-symbolic" if local.playing
                                 else "media-playback-start-symbolic")
        many = local.count > 1
        self._prev.set_sensitive(many)
        self._next.set_sensitive(many)
        self._play.set_sensitive(True)

    def _show_track(self) -> None:
        track = self._track
        self._title.remove_css_class("media-idle")
        self._player_label.set_label(track.identity)
        self._title.set_label(track.title or "—")
        self._artist.set_label(track.artist or track.album)
        self._load_art(track.art_url)
        self._play.set_icon_name("media-playback-pause-symbolic" if track.playing
                                 else "media-playback-start-symbolic")
        self._prev.set_sensitive(track.can_prev)
        self._next.set_sensitive(track.can_next)
        self._play.set_sensitive(track.can_play or track.can_pause)

    def _show_idle(self) -> None:
        """Nichts laeuft. Mit eingestelltem Ordner ist das kein Leerlauf,
        sondern eine Einladung: die Play-Taste startet ihn."""
        local = self._local
        self._title.add_css_class("media-idle")
        self._cover.set_paintable(None)
        self._art_url = ""
        self._play.set_icon_name("media-playback-start-symbolic")
        self._prev.set_sensitive(False)
        self._next.set_sensitive(False)

        if local is not None and local.count:
            self._player_label.set_label(local.label)
            self._title.set_label("Ordner abspielen")
            self._artist.set_label(str(local.folder))
            self._play.set_sensitive(True)
            return

        self._player_label.set_label("")
        self._play.set_sensitive(False)
        if local is not None:
            # Ein leerer oder unlesbarer Ordner ist ein Einstellungsfehler und
            # soll auch so aussehen, nicht wie "es laeuft halt nichts".
            self._title.set_label("Keine Musik im Ordner" if local.available
                                  else "Kein Media-Backend (GStreamer)")
            self._artist.set_label(str(local.folder))
            return
        # Ist ein Player fest eingestellt, sagen, dass *der* fehlt — sonst
        # sucht man den Fehler beim Modul statt beim nicht laufenden
        # Programm.
        wanted = self._watcher.preferred
        self._title.set_label(f"{wanted.capitalize()} laeuft nicht" if wanted
                              else "Nichts spielt")
        self._artist.set_label("")

    def _length_us(self) -> int:
        if self._use_local and self._local is not None:
            return self._local.length_us
        return self._track.length_us

    def _update_progress(self) -> None:
        if self._use_local and self._local is not None:
            length = self._local.length_us
            fraction = (max(0.0, min(1.0, self._local.position_us / length))
                        if length > 0 else 0.0)
        else:
            fraction = self._track.fraction
        self._progress.set_fraction(fraction)

    # ----- Cover -----

    def _load_art(self, url: str) -> None:
        if url == self._art_url:
            return
        self._art_url = url
        if not url:
            self._cover.set_paintable(None)
            return
        cached = self._art_cache.get(url)
        if cached is not None:
            self._cover.set_paintable(cached)
            return
        if url.startswith("file://"):
            try:
                texture = Gdk.Texture.new_from_file(Gio.File.new_for_uri(url))
            except GLib.Error:
                # Chromium legt Cover in /tmp ab und raeumt sie weg; ein
                # fehlendes Bild ist kein Fehler, nur kein Bild.
                self._cover.set_paintable(None)
                return
            self._remember(url, texture)
        elif url.startswith(("http://", "https://")):
            # Spotify liefert https-Adressen. Asynchron laden, damit die
            # Oberflaeche nicht am Netz haengt.
            Gio.File.new_for_uri(url).load_bytes_async(None, self._on_art_loaded, url)
        else:
            self._cover.set_paintable(None)

    def _on_art_loaded(self, gfile, result, url) -> None:
        try:
            data, _etag = gfile.load_bytes_finish(result)
            texture = Gdk.Texture.new_from_bytes(data)
        except GLib.Error:
            return
        # Zwischenzeitlich kann ein anderer Titel laufen.
        if url == self._art_url:
            self._remember(url, texture)

    def _remember(self, url: str, texture: Gdk.Texture) -> None:
        if len(self._art_cache) >= ART_CACHE_MAX:
            self._art_cache.pop(next(iter(self._art_cache)))
        self._art_cache[url] = texture
        self._cover.set_paintable(texture)

    # ----- Groesse -----

    def _check_size(self) -> bool:
        """Groesse geprueft, wenn sie sich geaendert hat.

        Nicht ueber ``do_size_allocate``: ``Gtk.Box`` hat einen
        Layout-Manager, und GTK4 leitet die Zuteilung an *den* weiter statt an
        die Vfunc des Widgets — die Ueberschreibung wurde nie gerufen
        (nachgemessen: null Aufrufe). ``WeightedColumn`` in ui/layout.py kommt
        nur damit durch, weil es ``set_layout_manager(None)`` setzt und die
        Zuteilung selbst macht.

        Der Sekundentakt reicht hier vollauf: die Modulgroesse aendert sich
        nur, wenn jemand das Layout speichert oder das Fenster den
        Vollbildmodus wechselt.
        """
        width, height = self.get_width(), self.get_height()
        if width > 0 and height > 0 and (width, height) != self._last_size:
            self._last_size = (width, height)
            self._decide(width, height)
        return GLib.SOURCE_REMOVE

    def _decide(self, width: int, height: int) -> None:
        """Was bei dieser Groesse sichtbar ist. Nur Zustandswechsel schreiben.

        Die Entscheidung haengt allein an der zugeteilten Groesse, nicht an
        der Mindestgroesse der Kinder — sonst koennte das Ausblenden eines
        Kindes die naechste Zuteilung aendern und die Sache liefe im Kreis.
        """
        vis = self._vis
        if vis["cover"]:
            cover = width >= COVER_OFF[0] and height >= COVER_OFF[1]
        else:
            cover = width >= COVER_ON[0] and height >= COVER_ON[1]
        cover = cover and self._show_cover and self._cover.get_paintable() is not None

        progress = height >= (PROGRESS_OFF_H if vis["progress"] else PROGRESS_ON_H)
        # Ohne sinnvolle Dauer (Live-Stream) waere der Balken immer leer.
        progress = progress and self._length_us() > 0

        header = height >= (HEADER_OFF_H if vis["header"] else HEADER_ON_H)

        self._vis = {"cover": cover, "progress": progress, "header": header}
        self._apply_visibility()

        if cover:
            # Quadratisch, hoechstens ein gutes Drittel der Breite.
            side = int(max(48, min(height * 0.62, width * 0.38)))
            if abs(side - self._cover_side) > 4:
                self._cover_side = side
                self._cover.set_size_request(side, side)

    def _apply_visibility(self) -> None:
        # Ob ueberhaupt ein Bild da ist, kann sich mit jedem Titel aendern —
        # die Groessenentscheidung in _decide() faellt aber nur, wenn sich das
        # Modul aendert. Ohne diese Pruefung bleibt nach einem Titel mit Cover
        # ein leerer Rahmen stehen, und das trifft den Musikordner staendig:
        # dort hat laengst nicht jedes Album ein Bild danebenliegen.
        has_art = self._cover.get_paintable() is not None
        self._cover.set_visible(self._vis["cover"] and has_art)
        self._progress.set_visible(self._vis["progress"])
        self._header.set_visible(self._vis["header"])

    # ----- Fenster-Schnittstelle -----

    def tick(self) -> None:
        self._check_size()
        if self._use_local:
            # Gtk.MediaStream kennt die Position selbst; nur zeichnen.
            if self._local is not None and self._local.playing:
                self._update_progress()
            return
        # Nur die Position abfragen; alles andere meldet der Player selbst.
        if self._track.present and self._track.playing and self._track.length_us > 0:
            self._track.position_us = self._watcher.position(self._track.player)
            self._update_progress()

    def update(self, snap) -> None:
        """Kommt vom Player ueber D-Bus, nicht aus dem Sensor-Snapshot."""

    def do_dispose(self):  # type: ignore[override]
        if self._refresh_source:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = 0
        self._watcher.stop()
        if self._local is not None:
            self._local.close()
        Gtk.Box.do_dispose(self)
