from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
USER_CONFIG_DIR = Path.home() / ".config" / "xeneon-edge"
APPS_FILE = CONFIG_DIR / "apps.json"
STYLE_CSS = Path(__file__).resolve().parent / "style.css"
# Mitgelieferte Icons, im Feld "icon" per Dateiname ansprechbar (z.B. "llm-start")
ICONS_DIR = Path(__file__).resolve().parent / "icons"

USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
USER_APPS_FILE = USER_CONFIG_DIR / "apps.json"
USER_SETTINGS_FILE = USER_CONFIG_DIR / "settings.json"
