"""Suggested stake: fractional Kelly on a shrunk edge. Run: python test_stake.py"""
from unittest import mock

from src import config, ev_calculator as ev, telegram_alerts


def test_stake_formula_and_examples():
    s = config.suggested_stake
    # 3.6% edge at 1.35 (a favourite): shrunk 1.26% / 0.35 = 3.6% Kelly -> quarter = 0.9% of $1000 = $9
    assert s(3.6, 1.35) == 9.0
    # 8% at 10.0 (longshot): shrunk 2.8% / 9 = 0.31% -> quarter = 0.08% = $0.78 -> min $1
    assert s(8.0, 10.0) == 1.0
    # 6% at 2.0: shrunk 2.1% / 1 -> quarter 0.525% = $5.25 -> $5
    assert s(6.0, 2.0) == 5.0
    assert s(6.0, 2.0) > s(6.0, 4.0)                              # shorter price -> bigger stake, same edge
    assert s(9.0, 2.0) > s(4.0, 2.0)                              # bigger edge -> bigger stake


def test_commission_cap_large_edge_and_off_switch():
    assert config.suggested_stake(6.0, 2.0, commission=0.06) > config.suggested_stake(6.0, 2.0, commission=0.0)  # smaller net odds -> higher Kelly share
    assert config.suggested_stake(500.0, 1.5) == config.BANKROLL * config.MAX_STAKE_PCT / 100                   # capped
    assert config.suggested_stake(8.0, 1.6, large_edge=True) == 6.0 and config.suggested_stake(8.0, 1.6) == 12.0             # halved
    assert config.suggested_stake(0.0, 2.0) == 0.0 and config.suggested_stake(-3, 2.0) == 0.0
    with mock.patch.object(config, "BANKROLL", 0.0):
        assert config.suggested_stake(6.0, 2.0) == 0.0
    with mock.patch.object(config, "BANKROLL", 3000.0):
        assert config.suggested_stake(6.0, 2.0) == 16.0           # scales with bankroll


def book(key, outcomes):
    return {"key": key, "title": key.title(), "markets": [{"key": "h2h", "outcomes": outcomes}]}


def test_stake_flows_into_opportunity_and_alert():
    soft = [book(k, [{"name": "Fav", "price": 1.22}, {"name": "Dog", "price": 4.5}]) for k in ("tab", "neds", "unibet", "ladbrokes_au")]
    e = {"id": "e1", "sport_key": "tennis_x", "commence_time": "2026-11-15T08:00:00Z", "home_team": "Fav", "away_team": "Dog",
         "bookmakers": soft + [book("pinnacle", [{"name": "Fav", "price": 1.19}, {"name": "Dog", "price": 5.3}]),
                               book("sportsbet", [{"name": "Fav", "price": 1.15}, {"name": "Dog", "price": 6.2}])]}
    opp = next(o for o in ev.find_positive_ev(e) if o["outcome"] == "Dog")
    assert opp["suggested_stake"] == config.suggested_stake(opp["ev_pct"], opp["price"], opp["commission"], False) >= 1
    msg = telegram_alerts.format_message(opp, "ab12")
    assert f"Suggested stake: ${opp['suggested_stake']:g}" in msg and f"/bet ab12 {opp['suggested_stake']:g}" in msg
    opp.pop("suggested_stake")                                      # old candidate without a stake: no crash, generic hint
    msg = telegram_alerts.format_message(opp, "ab12")
    assert "Suggested stake" not in msg and "/bet ab12 <stake>" in msg


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
