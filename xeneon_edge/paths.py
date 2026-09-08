import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
USER_CONFIG_DIR = Path.home() / ".config" / "xeneon-edge"
APPS_FILE = CONFIG_DIR / "apps.json"
STYLE_CSS = Path(__file__).resolve().parent / "style.css"
# Mitgelieferte Farbpaletten, eine TOML pro Theme (siehe theme.py)
THEMES_DIR = Path(__file__).resolve().parent / "themes"
# Mitgelieferte Icons, im Feld "icon" per Dateiname ansprechbar (z.B. "llm-start")
ICONS_DIR = Path(__file__).resolve().parent / "icons"

# Browser-Profil des Chart-Panels (Cookies, LocalStorage). Gehoert nach
# XDG_DATA_HOME, nicht in den Config-Ordner — und wird erst angelegt, wenn das
# Chart-Panel wirklich eine Session braucht (siehe ui/chart.py).
USER_DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
) / "xeneon-edge"
WEBKIT_DATA_DIR = USER_DATA_DIR / "webkit"
WEBKIT_CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
) / "xeneon-edge" / "webkit"

USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
USER_APPS_FILE = USER_CONFIG_DIR / "apps.json"
USER_SETTINGS_FILE = USER_CONFIG_DIR / "settings.json"
