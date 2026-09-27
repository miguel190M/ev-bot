"""Offline check of the daily digest: due-logic + message build with fake
odds. No network, no credits. Run: python test_daily_digest.py"""
from datetime import datetime, timedelta, timezone
from src import scheduling, daily_digest, odds_fetcher, telegram_commands, bets

# --- due logic (Sydney time, AEST in Sep 2026 = UTC+10) ---
at_8am = datetime(2026, 9, 26, 22, 0, tzinfo=timezone.utc)   # 8am Sun Syd
at_9am = datetime(2026, 9, 26, 23, 0, tzinfo=timezone.utc)   # 9am Sun Syd
assert scheduling.is_daily_digest_due("", 9, at_8am)[0] is False
due, today = scheduling.is_daily_digest_due("", 9, at_9am)
assert due and today == "2026-09-27"
assert scheduling.is_daily_digest_due("2026-09-27", 9, at_9am)[0] is False

# --- message build with a fake NBA event ---
now = at_9am
start = (now + timedelta(hours=10)).isoformat().replace("+00:00", "Z")
def book(key, title, home, away):
    return {"key": key, "title": title, "markets": [{"key": "h2h", "outcomes": [
        {"name": "Lakers", "price": home}, {"name": "Celtics", "price": away}]}]}
event = {"id": "ev1", "sport_key": "basketball_nba", "commence_time": start,
         "home_team": "Lakers", "away_team": "Celtics", "bookmakers": [
    book("sportsbet", "SportsBet", 2.40, 1.62),        # soft on Lakers
    book("betfair_ex_au", "Betfair", 2.10, 1.85),
    book("tab", "TAB", 2.05, 1.78), book("neds", "Neds", 2.02, 1.80),
    book("draftkings", "DraftKings", 2.08, 1.77)]}

odds_fetcher.get_sports_to_scan = lambda: ["basketball_nba", "aussierules_afl"]
odds_fetcher.get_events = lambda k: []  # AFL: nothing on -> no paid call
sent = []
telegram_commands.send_message = lambda t: sent.append(t)
bets.load_digest_state = lambda: {}
bets.save_digest_state = lambda s: None

candidates = {}
ledger = {"x1": {"status": "won", "stake": 50, "profit": 57.0, "resolved_at": (now - timedelta(hours=5)).isoformat()},
          "x2": {"status": "open", "stake": 40, "profit": None}}
cache = {"events": {"basketball_nba": [event]}, "remaining": "311", "credits_used": 0}

assert daily_digest.send_daily_digest_if_due(candidates, ledger, cache, now) is True
msg = sent[0]
print(msg, "\n")
assert "Lakers @ 2.4" in msg and "SportsBet" in msg
assert len(candidates) == 1  # slate pick registered so /bet works
assert "1W-0L" in msg and "$40 at risk" in msg and "311" in msg
assert len(msg) < 4096
print("All daily digest checks passed.")
