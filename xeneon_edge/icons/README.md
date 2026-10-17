# Bundled icons

Symbolic 16×16 SVGs shipped with the dashboard, found by name before the
icon theme is asked (see `xeneon_edge/ui/icons.py`). All of them were drawn
for this project and are covered by the repository's MIT license; nothing
here is copied from Adwaita, Yaru or another icon theme.

Drawing rules: filled shapes only, no strokes. GTK recolours symbolic SVGs
by injecting `fill: <colour> !important`, so a stroked outline would turn
into a solid block. Outlines are therefore rings (`fill-rule="evenodd"`).
The `-symbolic.svg` suffix is what makes GTK treat a file icon as symbolic
and tint it with the theme's text/accent colour.

| File | Used by |
|---|---|
| `llm-start-symbolic.svg`, `llm-stop-symbolic.svg`, `llm-vision-symbolic.svg` | launch-deck entries (`"icon": "llm-start"`) |
| `media-skip-backward-symbolic.svg`, `media-playback-start-symbolic.svg`, `media-playback-pause-symbolic.svg`, `media-skip-forward-symbolic.svg`, `folder-music-symbolic.svg` | Playback module buttons |

The media icons carry the freedesktop names on purpose: the theme icon of the
same name is the fallback if a bundled file ever goes missing, and a deck
entry may reference them too.
