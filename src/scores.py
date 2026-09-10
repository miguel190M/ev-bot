"""Fetch completed scores from the Odds API to automatically resolve open
bets - so /stats can report real, realized ROI without you manually typing
in every result."""

import requests

from . import config


def get_scores(sport_key: str, days_from: int = 3):
    """Completed scores from the past `days_from` days (1-3, costs 2 credits)
    plus any live games (included at no extra cost). Only call this for a
    sport when you actually have an open bet on it worth resolving."""
    url = f"{config.ODDS_API_BASE}/sports/{sport_key}/scores"
    params = {"apiKey": config.ODDS_API_KEY, "daysFrom": days_from, "dateFormat": "iso"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def extract_final_scores(score_event: dict):
    """Return {team_name: int_score} for a completed event, or None if it
    isn't finished yet / scores aren't available."""
    if not score_event.get("completed") or not score_event.get("scores"):
        return None
    try:
        return {s["name"]: int(s["score"]) for s in score_event["scores"]}
    except (KeyError, ValueError, TypeError):
        return None
