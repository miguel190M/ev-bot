"""Tests: other side of a held bet only alerts when it is an arbitrage, with the
equal-payout stake. Run: python test_arb.py"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import bets, breakdown, config, ev_calculator as ev, state, telegram_alerts
import main

NOW = datetime.now(timezone.utc)
T = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")


def book(key, outcomes, market="h2h"):
    return {"key": key, "title": key.title(), "markets": [{"key": market, "outcomes": outcomes}]}


def h2h(a, b):
    return [{"name": "Alpha", "price": a}, {"name": "Beta", "price": b}]


def event(books, sport="tennis_atp_x"):
    return {"id": "e1", "sport_key": sport, "commence_time": T, "home_team": "Alpha", "away_team": "Beta",
            "bookmakers": books}


def held(outcome="Alpha", price=2.10, stake=20.0, comm=0.0, status="open", market="h2h", book_="SportsBet"):
    return {"event_id": "e1", "sport_key": "tennis_atp_x", "market_key": market, "outcome": outcome,
            "price": price, "stake": stake, "commission": comm, "status": status, "bookmaker_title": book_}


SOFT = [book(k, h2h(1.90, 1.95)) for k in ("tab", "ladbrokes_au", "neds", "unibet")]


def test_is_opposing():
    o = {"event_id": "e1", "market_key": "h2h", "outcome": "Beta"}
    assert bets.is_opposing(o, held("Alpha"))
    assert not bets.is_opposing(o, held("Beta"))                              # same side
    assert not bets.is_opposing(o, held("Alpha", status="won"))               # only open bets count
    assert not bets.is_opposing(dict(o, event_id="e2"), held("Alpha"))
    t = {"event_id": "e1", "market_key": "totals", "outcome": "Under 224.5"}
    assert bets.is_opposing(t, held("Over 224.5", market="totals"))
    assert not bets.is_opposing(t, held("Over 227.5", market="totals"))       # different line
    assert not bets.is_opposing(t, held("Under 224.5", market="totals"))


def test_arb_found_with_equal_payout_stake():
    # hold Alpha @2.10 $20 (Sportsbet, no commission); Betfair Beta @2.30, 6% commission
    ev_ = event(SOFT + [book("betfair_ex_au", h2h(2.0, 2.30))])
    arbs = ev.find_hedge_arbs(ev_, [("a1", held())])
    assert len(arbs) == 1
    o, a = arbs[0], arbs[0]["arb"]
    eff_b = 1 + 1.30 * 0.94
    assert o["outcome"] == "Beta" and o["bookmaker_key"] == "betfair_ex_au" and o["price"] == 2.30
    assert abs(a["stake"] - round(20 * 2.10 / eff_b, 2)) < 0.011
    assert abs(a["payout"] - 42.0) < 1e-9
    # same money back whichever side wins
    assert abs(a["stake"] * eff_b - 42.0) < 0.05
    assert abs(a["profit"] - (42.0 - 20 - a["stake"])) < 0.02 and a["profit"] > 0
    assert a["held_ids"] == ["a1"] and a["held_stake"] == 20.0


def test_no_arb_when_prices_do_not_cross():
    ev_ = event(SOFT + [book("betfair_ex_au", h2h(2.0, 1.95))])
    assert ev.find_hedge_arbs(ev_, [("a1", held())]) == []
    # commission can turn a raw arb into none: raw 1/2.1 + 1/1.95 = 0.989, but Betfair 1.95 nets only 1.893 -> 1.004
    ev2 = event(SOFT + [book("betfair_ex_au", h2h(2.0, 1.95))])
    assert ev.find_hedge_arbs(ev2, [("a1", held())]) == []


def test_three_way_market_never_arbs():
    three = [{"name": "Alpha", "price": 2.1}, {"name": "Draw", "price": 3.4}, {"name": "Beta", "price": 9.0}]
    ev_ = event([book(k, three) for k in ("tab", "neds", "unibet", "ladbrokes_au", "betfair_ex_au")], "soccer_epl")
    assert ev.find_hedge_arbs(ev_, [("a1", held())]) == []


def test_two_bets_on_same_side_are_one_position():
    ev_ = event(SOFT + [book("betfair_ex_au", h2h(2.0, 2.30))])
    one = ev.find_hedge_arbs(ev_, [("a1", held(stake=40.0))])[0]["arb"]
    two = ev.find_hedge_arbs(ev_, [("a1", held(stake=20.0)), ("a2", held(stake=20.0))])[0]["arb"]
    assert abs(one["stake"] - two["stake"]) < 1e-9 and abs(one["profit"] - two["profit"]) < 1e-9
    assert two["held_ids"] == ["a1", "a2"] and two["held_stake"] == 40.0


def test_arb_threshold_setting():
    ev_ = event(SOFT + [book("betfair_ex_au", h2h(2.0, 2.30))])
    with mock.patch.object(config, "ARB_MIN_PROFIT_PCT", 50.0):
        assert ev.find_hedge_arbs(ev_, [("a1", held())]) == []


def test_alert_text_state_key_and_tag():
    ev_ = event(SOFT + [book("betfair_ex_au", h2h(2.0, 2.30))])
    opp = ev.find_hedge_arbs(ev_, [("a1", held())])[0]
    msg = telegram_alerts.format_message(opp, "zz99")
    assert msg.startswith("🔒 ARBITRAGE") and "You hold: Alpha @ 2.1 (SportsBet) $20" in msg
    assert "Best size: $" in msg and "guaranteed profit" in msg and f"/bet zz99 {opp['arb']['stake']:.2f}" in msg
    plain = dict(opp); plain.pop("arb")
    assert state.make_key(opp) == state.make_key(plain) + ":arb"
    L = {}
    _, bet = bets.place_bet("zz99", opp["arb"]["stake"], opp, L)
    assert bet["arb_hedge"] is True
    bet["status"], bet["profit"] = "won", 1.0
    assert "Arb hedge: 1-0" in breakdown.build(L, "flag")


def _scan(ledger, events, finder=None):
    alerts = []
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            with mock.patch.object(main.odds_fetcher, "get_sports_to_scan", return_value=["tennis_atp_x"]), \
                 mock.patch.object(main.odds_fetcher, "get_events", return_value=events), \
                 mock.patch.object(main.odds_fetcher, "get_odds", return_value=(events, "19000", "2")), \
                 mock.patch.object(main.telegram_alerts, "send_alert",
                                   side_effect=lambda o, bid: alerts.append((o["outcome"], bool(o.get("arb"))))):
                main.run_scan({}, ledger, {"events": {}, "remaining": None, "credits_used": 0})
        finally:
            os.chdir(old)
    return alerts


def test_scan_end_to_end():
    # Pinnacle says Beta is worth ~2.0; Sportsbet offers Beta 2.30 -> normal +EV on Beta, and an arb vs held Alpha.
    books = SOFT + [book("pinnacle", h2h(1.95, 1.97)), book("betfair_ex_au", h2h(2.0, 2.30))]
    ev_ = [event(books)]
    # nothing held: Beta alerts as a normal +EV pick
    assert _scan({}, ev_) == [("Beta", False)]
    # holding Alpha @2.10: the normal Beta alert is replaced by the arb version only
    assert _scan({"a1": held()}, ev_) == [("Beta", True)]
    # holding Alpha at a price where no arb exists: Beta is silent
    assert _scan({"a1": held(price=1.80)}, ev_) == []
    # already holding BOTH sides: nothing more to alert
    both = {"a1": held(), "b1": held("Beta", price=2.30, book_="Betfair")}
    assert _scan(both, ev_) == []


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
