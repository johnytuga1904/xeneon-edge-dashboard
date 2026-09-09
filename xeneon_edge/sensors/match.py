"""Next/last match of a configured team via ESPN public scoreboard.

Port of WidgetsSource.cs TryFetchNextMatch(): hits the league scoreboard
with a ±-day window and picks the upcoming match (or, if nothing is
scheduled, the most recent past one with score). League code and team ID
are ESPN's (e.g. "por.1" and "1929"); both come from the topbar widget
config, nothing is hard-wired here any more.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore



def _url(league: str) -> str:
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=3)).strftime("%Y%m%d")
    to = (now + timedelta(days=21)).strftime("%Y%m%d")
    return (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
        f"?dates={frm}-{to}"
    )


def fetch_next_match(league: str, team_id: str, timeout: float = 4.0) -> dict | None:
    if requests is None or not league or not team_id:
        return None
    team_id = str(team_id)
    try:
        r = requests.get(_url(league), timeout=timeout)
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
                if tid == team_id:
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
