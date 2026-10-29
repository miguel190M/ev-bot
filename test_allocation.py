"""Tests for per-sport scan allocation (costs, niche far-zone, throttled popular
sports). Run: python test_allocation.py"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import config, scheduling
import main

NOW = datetime.now(timezone.utc)


def test_costs_per_pull():
    def cost(k):
        return len(config.get_regions_for_sport(k).split(",")) * len(config.get_markets_for_sport(k).split(","))
    assert cost("basketball_nba") == 3                  # au,us,eu
    for k in ("americanfootball_nfl", "baseball_mlb", "icehockey_nhl", "soccer_epl",
              "soccer_germany_bundesliga", "soccer_uefa_champs_league", "boxing_boxing", "cricket_big_bash"):
        assert cost(k) == 2, k


def test_niche_windows_and_intervals():
    for k in ("boxing_boxing", "mma_mixed_martial_arts", "cricket_odi", "tennis_atp_x", "cricket_big_bash"):
        assert config.get_far_window_hours(k) == 24 and config.get_far_interval_hours(k) == 1
    assert config.get_far_window_hours("soccer_epl") == 12 and config.get_far_interval_hours("soccer_epl") == 4
    assert "cricket_big_bash" in config.FIXED_SPORTS


def test_throttle_membership():
    assert config.get_near_interval_minutes("basketball_nba") == 0          # NBA unthrottled
    assert config.get_near_interval_minutes("soccer_epl") == 120
    assert config.get_near_interval_minutes("boxing_boxing") == 0
    assert config.get_near_interval_minutes("aussierules_afl") == 0


def test_slack_lets_a_slightly_early_run_through():
    last = (NOW - timedelta(minutes=57)).isoformat()
    assert not scheduling.is_far_check_due(last, 1.0, NOW)
    assert scheduling.is_far_check_due(last, 1.0, NOW, slack_minutes=5)
    assert not scheduling.is_far_check_due((NOW - timedelta(minutes=50)).isoformat(), 1.0, NOW, slack_minutes=5)


def _ev(hours_ahead, eid="e1"):
    t = (NOW + timedelta(hours=hours_ahead)).isoformat().replace("+00:00", "Z")
    return {"id": eid, "commence_time": t, "home_team": "H", "away_team": "A", "bookmakers": []}


def _scan(sports, events_by_sport, ledger=None):
    pulled = []

    def get_odds(k):
        pulled.append(k)
        return events_by_sport[k], "19000", "2"
    with mock.patch.object(main.odds_fetcher, "get_sports_to_scan", return_value=sports), \
         mock.patch.object(main.odds_fetcher, "get_events", side_effect=lambda k: events_by_sport[k]), \
         mock.patch.object(main.odds_fetcher, "get_odds", side_effect=get_odds):
        main.run_scan({}, ledger or {}, {"events": {}, "remaining": None, "credits_used": 0})
    return pulled


def test_run_scan_throttles_popular_not_nba_and_niche_far_is_hourly():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            ev = {"soccer_epl": [_ev(1)], "basketball_nba": [_ev(1)],
                  "boxing_boxing": [_ev(20)], "soccer_spain_la_liga": [_ev(20)]}
            sports = list(ev)
            assert sorted(_scan(sports, ev)) == ["basketball_nba", "boxing_boxing", "soccer_epl"]   # la liga 20h: outside its 12h far window
            # 30 minutes later (state carried in data/): EPL throttled, NBA still pulled, boxing (1h) not due
            import json
            st = json.load(open("data/far_scan_state.json"))
            for k in list(st):
                st[k] = (NOW - timedelta(minutes=30)).isoformat()
            json.dump(st, open("data/far_scan_state.json", "w"))
            assert _scan(sports, ev) == ["basketball_nba"]
            # 65 minutes after the first run: boxing due again, EPL still throttled
            for k in list(st):
                st[k] = (NOW - timedelta(minutes=65)).isoformat()
            json.dump(st, open("data/far_scan_state.json", "w"))
            assert sorted(_scan(sports, ev)) == ["basketball_nba", "boxing_boxing"]
            # 2h+ later EPL is due too
            for k in list(st):
                st[k] = (NOW - timedelta(minutes=125)).isoformat()
            json.dump(st, open("data/far_scan_state.json", "w"))
            assert "soccer_epl" in _scan(sports, ev)
        finally:
            os.chdir(old)


def test_open_bet_soon_disables_throttle_for_that_sport():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            import json
            os.makedirs("data")
            json.dump({"near:soccer_epl": (NOW - timedelta(minutes=10)).isoformat()}, open("data/far_scan_state.json", "w"))
            ev = {"soccer_epl": [_ev(1, "x")]}
            assert _scan(["soccer_epl"], ev) == []                      # throttled
            bet = {"status": "open", "sport_key": "soccer_epl", "event_id": "x",
                   "commence_time": ev["soccer_epl"][0]["commence_time"], "outcome": "H", "market_key": "h2h"}
            assert _scan(["soccer_epl"], ev, {"b": bet}) == ["soccer_epl"]  # closing line still captured
        finally:
            os.chdir(old)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
