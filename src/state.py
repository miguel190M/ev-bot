"""Simple JSON-file state so we don't re-alert the same opportunity every run.
Persisted by committing data/state.json back to the repo after each GitHub
Actions run (see .github/workflows/scan.yml)."""

import json
from pathlib import Path

from . import config


def load_state() -> dict:
    path = Path(config.STATE_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state: dict):
    path = Path(config.STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def make_key(opp: dict) -> str:
    return f"{opp['event_id']}:{opp['bookmaker_key']}:{opp['outcome']}"


def filter_new_or_changed(opportunities: list[dict], state: dict) -> list[dict]:
    """Only return opportunities that are new, or whose EV% has moved by at
    least MIN_EV_DELTA_TO_REALERT percentage points since the last alert -
    avoids spamming on tiny odds jitter."""
    fresh = []
    for opp in opportunities:
        key = make_key(opp)
        prev = state.get(key)
        if prev is None or abs(opp["ev_pct"] - prev["ev_pct"]) >= config.MIN_EV_DELTA_TO_REALERT:
            fresh.append(opp)
        state[key] = {"ev_pct": opp["ev_pct"], "commence_time": opp["commence_time"]}
    return fresh


def prune_expired(state: dict, now_iso: str):
    """Drop state entries for events that have already started, so keys don't
    grow forever and so a repeat matchup later isn't seen as 'already alerted'."""
    for key in list(state.keys()):
        if state[key].get("commence_time", "9999") < now_iso:
            del state[key]
