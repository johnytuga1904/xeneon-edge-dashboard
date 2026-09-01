"""SL Benfica next/last match via ESPN public scoreboard.

Port of WidgetsSource.cs TryFetchNextMatch(): hits the Primeira Liga
scoreboard with a ±-day window and picks the upcoming match (or, if
nothing is scheduled, the most recent past one with score).
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore

_BENFICA_ID = "1929"


def _url() -> str:
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=3)).strftime("%Y%m%d")
    to = (now + timedelta(days=21)).strftime("%Y%m%d")
    return (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/por.1/scoreboard"
        f"?dates={frm}-{to}"
    )


def fetch_next_match(timeout: float = 4.0) -> dict | None:
    if requests is None:
        return None
    try:
        r = requests.get(_url(), timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    events = data.get("events") or []
    now = datetime.now(timezone.utc)
    future: dict | None = None
    last_past: dict | None = None

    for ev in events:
        date_str = ev.get("date")
        if not date_str:
            continue
        try:
            when = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            when = when.astimezone(timezone.utc)
        except ValueError:
            continue

        opponent = "?"
        home = True
        is_benfica = False
        slb_score: str | None = None
        opp_score: str | None = None

        comps = ev.get("competitions") or []
        if comps:
            teams = (comps[0] or {}).get("competitors") or []
            for t in teams:
                tid = str(t.get("id") or "")
                side = t.get("homeAway") or ""
                sc = t.get("score")
                if isinstance(sc, dict):
                    sc = sc.get("value") or sc.get("displayValue")
                sc = str(sc) if sc is not None else None
                if tid == _BENFICA_ID:
                    home = side == "home"
                    slb_score = sc
                    is_benfica = True
                else:
                    name = (t.get("team") or {}).get("displayName")
                    if name:
                        opponent = name
                    opp_score = sc

        if not is_benfica:
            continue

        competition = "Match"
        league = ev.get("league") or {}
        if league.get("abbreviation"):
            competition = league["abbreviation"]
        else:
            season = ev.get("season") or {}
            if season.get("displayName"):
                competition = season["displayName"]

        if when >= now:
            if future is None or when < datetime.fromisoformat(future["kickoff_utc"]):
                future = {
                    "opponent": opponent,
                    "kickoff_utc": when.isoformat(),
                    "is_home": home,
                    "competition": competition,
                    "is_past": False,
                    "score": None,
                }
        else:
            score = None
            if slb_score is not None and opp_score is not None:
                score = f"{slb_score}-{opp_score}" if home else f"{opp_score}-{slb_score}"
            if last_past is None or when > datetime.fromisoformat(last_past["kickoff_utc"]):
                last_past = {
                    "opponent": opponent,
                    "kickoff_utc": when.isoformat(),
                    "is_home": home,
                    "competition": competition,
                    "is_past": True,
                    "score": score,
                }

    return future or last_past
