"""Offline check of bet tagging + /breakdown. Run: python test_breakdown.py"""
from datetime import datetime, timedelta, timezone
from src import bets, breakdown, telegram_commands as tc

now = datetime.now(timezone.utc)
opp = {"event_id": "e1", "sport_key": "rugbyleague_nrl", "commence_time": (now + timedelta(hours=14)).isoformat(),
       "home_team": "Storm", "away_team": "Panthers", "market_key": "h2h", "bookmaker_key": "betfair_ex_au",
       "bookmaker_title": "Betfair", "outcome": "Storm", "price": 2.3, "commission": 0.10, "ev_pct": 6.2,
       "anchor": "retail_consensus", "source": "daily_digest", "alerted_at": now.isoformat()}
ledger = {}
_, b = bets.place_bet("abcd", 50, opp, ledger)
assert b["source"] == "daily_digest" and b["lead_hours"] == 14.0 and b["bookmaker_key"] == "betfair_ex_au"

# a legacy bet with none of the new fields must still work
ledger["old"] = {"sport_key": "basketball_nba", "bookmaker_title": "SportsBet", "market_key": "h2h",
                 "ev_pct": 3.4, "stake": 20, "status": "lost", "profit": -20, "net_clv_pct": -1.2}
b.update(status="won", profit=58.5, net_clv_pct=2.8)

assert tc.parse_breakdown_command("/breakdown") == "all"
assert tc.parse_breakdown_command("/Breakdown sport") == "sport"
assert tc.parse_breakdown_command("/bet abcd 5") is None

out = breakdown.build(ledger)
print(out, "\n")
assert "digest: 1-0" in out and "live: 0-1" in out and "12h+" in out and "unknown" in out
assert "Unknown breakdown" in breakdown.build(ledger, "colour")
print(breakdown.build(ledger, "lead"))
print("\nAll breakdown checks passed.")
