"""Open-Meteo weather (Wohlen, CH) — same approach as the Windows app."""
from __future__ import annotations

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore

_LAT = 47.3464
_LON = 8.2752
_URL = (
    f"https://api.open-meteo.com/v1/forecast?latitude={_LAT}&longitude={_LON}"
    "&current=temperature_2m,weather_code"
)

_SYMBOLS = {
    0: "☀", 1: "☀", 2: "⛅", 3: "☁",
    45: "\U0001F32B", 48: "\U0001F32B",
    51: "\U0001F326", 53: "\U0001F326", 55: "\U0001F326",
    61: "\U0001F327", 63: "\U0001F327", 65: "\U0001F327",
    71: "❄", 73: "❄", 75: "❄",
    80: "\U0001F326", 81: "\U0001F327", 82: "⛈",
    95: "⛈", 96: "⛈", 99: "⛈",
}


def fetch_weather(timeout: float = 4.0) -> dict | None:
    if requests is None:
        return None
    try:
        r = requests.get(_URL, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    cur = data.get("current") or {}
    temp = cur.get("temperature_2m")
    code = cur.get("weather_code")
    if temp is None or code is None:
        return None
    return {
        "temp_c": float(temp),
        "code": int(code),
        "symbol": _SYMBOLS.get(int(code), "?"),
    }
