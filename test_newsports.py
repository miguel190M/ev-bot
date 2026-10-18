"""Tests for cricket discovery, new fixed sports and the no-auto-score guard.
Run: python test_newsports.py"""
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import config, odds_fetcher, daily_digest
import main


def test_discovery_picks_tennis_and_cricket_not_others():
    sports = [
        {"key": "tennis_atp_x", "group": "Tennis", "active": True},
        {"key": "cricket_test_match", "group": "Cricket", "active": True},
        {"key": "cricket_ipl", "group": "Cricket", "active": False},
        {"key": "soccer_epl", "group": "Soccer", "active": True},
    ]
    with mock.patch.object(odds_fetcher, "get_active_sports", return_value=sports):
        keys = odds_fetcher.get_sports_to_scan()
    assert "tennis_atp_x" in keys and "cricket_test_match" in keys
    assert "cricket_ipl" not in keys                 # inactive
    assert keys.count("soccer_epl") == 1             # fixed only, not duplicated
    for k in ("soccer_germany_bundesliga", "soccer_australia_aleague",
              "mma_mixed_martial_arts", "boxing_boxing"):
        assert k in keys


def test_soccer_leagues_get_totals_and_sharp_region():
    assert config.get_markets_for_sport("soccer_germany_bundesliga") == "h2h,totals"
    assert config.get_markets_for_sport("soccer_australia_aleague") == "h2h,totals"
    assert "eu" in config.get_regions_for_sport("cricket_test_match").split(",")


def test_labels():
    assert daily_digest._sport_label("cricket_big_bash") == "Cricket Big Bash"
    assert daily_digest._sport_label("mma_mixed_martial_arts") == "MMA"
    assert daily_digest._sport_label("soccer_germany_bundesliga") == "Bundesliga"


def _bet(sport, hours_ago):
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"status": "open", "sport_key": sport, "event_id": "e1",
            "commence_time": t.isoformat().replace("+00:00", "Z")}


def test_unresolvable_and_stale_bets_do_not_spend_credits():
    ledger = {"a": _bet("mma_mixed_martial_arts", 10), "b": _bet("cricket_odi", 10),
              "c": _bet("boxing_boxing", 10), "d": _bet("basketball_nba", 24 * 5)}
    with mock.patch.object(main.scores, "get_scores") as gs:
        main.resolve_open_bets(ledger)
    assert gs.call_count == 0


def test_normal_sport_still_fetches_scores():
    ledger = {"a": _bet("basketball_nba", 10)}
    with mock.patch.object(main.scores, "get_scores", return_value=[]) as gs:
        main.resolve_open_bets(ledger)
    assert gs.call_count == 1


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
