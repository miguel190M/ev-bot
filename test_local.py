"""Sanity-check the EV math against synthetic data - no API key or network
needed. Run: python test_local.py"""
from src import ev_calculator

# --- Test 1: Betfair anchor path ---
# Betfair back/lay implies Lakers are ~65% (mid of 1/1.56 and 1/1.52).
# Sportsbet and TAB roughly agree. Neds is offering a price way better than
# that fair line -> should be flagged, anchored on betfair_exchange.
event_with_betfair = {
    "id": "test_event_1",
    "sport_key": "basketball_nba",
    "commence_time": "2026-08-01T09:00:00Z",
    "home_team": "Lakers",
    "away_team": "Celtics",
    "bookmakers": [
        {"key": "betfair_ex_au", "title": "Betfair Exchange", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Lakers", "price": 1.56}, {"name": "Celtics", "price": 2.62}]},
            {"key": "h2h_lay", "outcomes": [{"name": "Lakers", "price": 1.58}, {"name": "Celtics", "price": 2.68}]},
        ]},
        {"key": "sportsbet", "title": "Sportsbet", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Lakers", "price": 1.54}, {"name": "Celtics", "price": 2.55}]}
        ]},
        {"key": "tab", "title": "TAB", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Lakers", "price": 1.52}, {"name": "Celtics", "price": 2.60}]}
        ]},
        {"key": "neds", "title": "Neds", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Lakers", "price": 1.75}, {"name": "Celtics", "price": 2.20}]}
        ]},
    ],
}

opps = ev_calculator.find_positive_ev(event_with_betfair)
print("Test 1: Betfair-anchored event")
for o in opps:
    print(f"  [{o['anchor']}] {o['bookmaker_title']}: {o['outcome']} @ {o['price']} "
          f"(fair ~{o['fair_odds']}, {o['ev_pct']}% EV)")
assert all(o["anchor"] == "betfair_exchange" for o in opps), "expected betfair anchor"
assert any(o["bookmaker_key"] == "neds" and o["outcome"] == "Lakers" for o in opps), "expected Neds Lakers flagged"
assert not any(o["bookmaker_key"] == "betfair_ex_au" for o in opps), "betfair should never be its own target"
print("  ✅ passed\n")

# --- Test 2: fallback path (no Betfair data on this event) ---
event_no_betfair = {
    "id": "test_event_2",
    "sport_key": "rugbyleague_nrl",
    "commence_time": "2026-08-02T09:00:00Z",
    "home_team": "Broncos",
    "away_team": "Storm",
    "bookmakers": [
        {"key": "sportsbet", "title": "Sportsbet", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Broncos", "price": 1.90}, {"name": "Storm", "price": 1.95}]}
        ]},
        {"key": "tab", "title": "TAB", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Broncos", "price": 1.88}, {"name": "Storm", "price": 1.97}]}
        ]},
        {"key": "ladbrokes", "title": "Ladbrokes", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Broncos", "price": 2.10}, {"name": "Storm", "price": 1.78}]}
        ]},
    ],
}

opps2 = ev_calculator.find_positive_ev(event_no_betfair)
print("Test 2: no Betfair data - should fall back to retail consensus")
for o in opps2:
    print(f"  [{o['anchor']}] {o['bookmaker_title']}: {o['outcome']} @ {o['price']} "
          f"(fair ~{o['fair_odds']}, {o['ev_pct']}% EV)")
assert all(o["anchor"] == "retail_consensus" for o in opps2), "expected retail_consensus fallback"
assert len(opps2) > 0, "expected the Ladbrokes outlier to be flagged"
print("  ✅ passed\n")

print("All tests passed.")
