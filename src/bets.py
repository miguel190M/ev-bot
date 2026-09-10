"""Bet ledger: log bets the user actually placed after seeing an alert, and
resolve them automatically once the game finishes, using the Odds API's
scores endpoint. This is what lets /stats report real, realized ROI instead
of just alerted-but-unacted-on EV.

Two files back this:
  data/alert_candidates.json - every alerted opportunity, keyed by a short id,
    kept only until its event starts (you can't meaningfully log a pre-game
    bet on something already underway).
  data/bets.json - bets actually logged via /bet, keyed by the same short id
    (or a suffixed variant on id collision), each with a status of
    open / won / lost / void.
"""

import hashlib
import json
from pathlib import Path

ALERTS_FILE = "data/alert_candidates.json"
BETS_FILE = "data/bets.json"
DIGEST_STATE_FILE = "data/digest_state.json"


def _load(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def load_candidates() -> dict:
    return _load(ALERTS_FILE)


def save_candidates(candidates: dict):
    _save(ALERTS_FILE, candidates)


def short_id(opp: dict, existing: dict) -> str:
    """A short, stable id derived from the opportunity, long enough to avoid
    colliding with whatever's currently in `existing`."""
    base = f"{opp['event_id']}:{opp['bookmaker_key']}:{opp['outcome']}"
    digest = hashlib.sha1(base.encode()).hexdigest()
    for length in (4, 5, 6, 8, 12):
        candidate = digest[:length]
        if candidate not in existing:
            return candidate
    return digest  # astronomically unlikely fallback


def register_candidate(opp: dict, candidates: dict) -> str:
    """Store this alerted opportunity so a later /bet command can reference
    it by a short id, and return that id."""
    sid = short_id(opp, candidates)
    candidates[sid] = opp
    return sid


def prune_candidates(candidates: dict, now_iso: str):
    for sid in list(candidates.keys()):
        if candidates[sid]["commence_time"] < now_iso:
            del candidates[sid]


def load_bets() -> dict:
    return _load(BETS_FILE)


def save_bets(bets: dict):
    _save(BETS_FILE, bets)


def load_digest_state() -> dict:
    return _load(DIGEST_STATE_FILE)


def save_digest_state(state: dict):
    _save(DIGEST_STATE_FILE, state)


def place_bet(sid: str, stake: float, opp: dict, bets: dict) -> tuple[str, dict]:
    """Record a new bet against an alerted opportunity. Returns (bet_id, bet)."""
    bet_id = sid if sid not in bets else f"{sid}-{sum(1 for k in bets if k.startswith(sid))}"
    bet = {
        "event_id": opp["event_id"],
        "sport_key": opp["sport_key"],
        "commence_time": opp["commence_time"],
        "home_team": opp.get("home_team"),
        "away_team": opp.get("away_team"),
        "bookmaker_title": opp["bookmaker_title"],
        "outcome": opp["outcome"],
        "price": opp["price"],
        "ev_pct": opp["ev_pct"],
        "anchor": opp["anchor"],
        "stake": stake,
        "status": "open",
        "profit": None,
    }
    bets[bet_id] = bet
    return bet_id, bet


def resolve_bet(bet: dict, final_scores: dict) -> bool:
    """final_scores: {team_name: int_score}. Mutates bet in place if it can
    be resolved. Returns True if the bet's status changed."""
    home, away = bet.get("home_team"), bet.get("away_team")
    if home not in final_scores or away not in final_scores:
        return False

    home_score, away_score = final_scores[home], final_scores[away]
    if home_score > away_score:
        winner = home
    elif away_score > home_score:
        winner = away
    else:
        winner = "Draw"  # only a real outcome to bet on in sports like soccer

    if bet["outcome"] == winner:
        bet["status"] = "won"
        bet["profit"] = round(bet["stake"] * (bet["price"] - 1), 2)
    elif winner == "Draw":
        # a tie happened but this market never offered "Draw" as a bettable
        # outcome (e.g. NBA/NFL/AFL/NRL/tennis) - can't score this cleanly
        bet["status"] = "void"
        bet["profit"] = 0.0
    else:
        bet["status"] = "lost"
        bet["profit"] = round(-bet["stake"], 2)
    return True


def compute_stats(bets: dict) -> dict:
    won = [b for b in bets.values() if b["status"] == "won"]
    lost = [b for b in bets.values() if b["status"] == "lost"]
    void = [b for b in bets.values() if b["status"] == "void"]
    open_bets = [b for b in bets.values() if b["status"] == "open"]

    # Void bets (a tie on a market that never offered "Draw") never had stake
    # genuinely at risk, so they're excluded from win/loss and ROI math -
    # counted as resolved, but kept separate from the profit calculation.
    decided = won + lost
    total_staked = sum(b["stake"] for b in decided)
    total_profit = sum(b["profit"] for b in decided)
    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0
    return {
        "resolved_count": len(decided) + len(void),
        "open_count": len(open_bets),
        "wins": len(won),
        "losses": len(lost),
        "voids": len(void),
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round(roi, 2),
    }
