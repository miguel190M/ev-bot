import requests

from . import config


def get_active_sports() -> list[dict]:
    """List in-season sports. This call is free (doesn't cost quota)."""
    url = f"{config.ODDS_API_BASE}/sports"
    resp = requests.get(url, params={"apiKey": config.ODDS_API_KEY}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_tennis_sport_keys() -> list[str]:
    """Tennis has no single fixed sport key - each active ATP/WTA tournament
    is its own key (e.g. tennis_atp_wimbledon). Discover the currently active
    ones each run."""
    sports = get_active_sports()
    return [s["key"] for s in sports if s.get("group") == "Tennis" and s.get("active")]


def get_sports_to_scan() -> list[str]:
    return config.FIXED_SPORTS + get_tennis_sport_keys()


def get_events(sport_key: str) -> list[dict]:
    """List upcoming events (no odds) for a sport. This call is free (doesn't
    cost quota) - used to check what's coming up before spending credits on
    the /odds call."""
    url = f"{config.ODDS_API_BASE}/sports/{sport_key}/events"
    resp = requests.get(url, params={"apiKey": config.ODDS_API_KEY}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_odds(sport_key: str):
    """Fetch h2h odds for one sport key / region(s). Costs
    [markets] x [regions] credits - 1 credit for single-region sports, 2 for
    sports with a region override (see config.SPORT_REGION_OVERRIDES)."""
    url = f"{config.ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": config.get_regions_for_sport(sport_key),
        "markets": config.MARKET,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    remaining = resp.headers.get("x-requests-remaining")
    used = resp.headers.get("x-requests-last", "0")
    return resp.json(), remaining, used
