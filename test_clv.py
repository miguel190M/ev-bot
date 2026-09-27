"""Offline check of closing-line capture + edge cap. Run: python test_clv.py"""
from datetime import datetime, timedelta, timezone
from src import clv, odds_fetcher, ev_calculator

now = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)
iso = lambda dt: dt.isoformat().replace("+00:00", "Z")

def book(key, a, b):
    return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": [
        {"name": "Storm", "price": a}, {"name": "Panthers", "price": b}]}]}

def event(eid, sport, start, books):
    return {"id": eid, "sport_key": sport, "commence_time": iso(start),
            "home_team": "Storm", "away_team": "Panthers", "bookmakers": books}

refs = [book("tab", 2.0, 1.85), book("neds", 2.05, 1.80), book("ladbrokes_au", 2.02, 1.82)]
soon = event("e_soon", "rugbyleague_nrl", now + timedelta(minutes=30), refs)
later = event("e_later", "aussierules_afl", now + timedelta(hours=5), refs)

bet = lambda eid, sport, start: {"event_id": eid, "sport_key": sport, "commence_time": iso(start),
                                  "outcome": "Storm", "market_key": "h2h", "status": "open"}
ledger = {"a": bet("e_soon", "rugbyleague_nrl", now + timedelta(minutes=30)),
          "b": bet("e_later", "aussierules_afl", now + timedelta(hours=5)),
          "c": bet("e_past", "rugbyleague_nrl", now - timedelta(minutes=5))}

calls = []
def fake_get_odds(sport):
    calls.append(sport)
    return ([soon] if sport == "rugbyleague_nrl" else [later]), "300", "1"
odds_fetcher.get_odds = fake_get_odds

cache = {"events": {}, "remaining": None, "credits_used": 0}
used = clv.capture_closing(ledger, cache, now)
assert calls == ["rugbyleague_nrl"], calls        # only the imminent sport costs a credit
assert used == 1
assert ledger["a"]["closing_fair_odds"]            # imminent bet captured
assert "closing_fair_odds" not in ledger["b"]      # 5h out, not due, not cached
assert "closing_fair_odds" not in ledger["c"]      # already started - never overwritten

# cached sport refreshes for free
cache2 = {"events": {"aussierules_afl": [later], "rugbyleague_nrl": [soon]}, "remaining": None, "credits_used": 0}
calls.clear()
assert clv.capture_closing(ledger, cache2, now) == 0 and calls == []
assert ledger["b"]["closing_fair_odds"]

# edge cap: Sportsbet at 3.5 vs fair ~2.0 is a ~70% "edge" -> suppressed
capped = event("e_cap", "rugbyleague_nrl", now + timedelta(hours=1), refs + [book("sportsbet", 3.5, 1.3)])
assert ev_calculator.find_positive_ev(capped) == []
ok = event("e_ok", "rugbyleague_nrl", now + timedelta(hours=1), refs + [book("sportsbet", 2.2, 1.7)])
assert len(ev_calculator.find_positive_ev(ok)) == 1  # normal edge still alerts
print("All CLV capture / edge cap checks passed.")
