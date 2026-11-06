"""Tests for logging the price you actually got: /bet <id> <stake> @<price> and /price.
Run: python test_price.py"""
from unittest import mock

from src import bets, telegram_commands as tc
import main

T = "2099-01-01T00:00:00Z"


def opp(price=1.71, ev=5.83, comm=0.0, book="SportsBet"):
    return {"event_id": "e1", "sport_key": "boxing_boxing", "commence_time": T, "home_team": "H", "away_team": "A",
            "market_key": "h2h", "bookmaker_key": book.lower(), "bookmaker_title": book, "outcome": "H",
            "price": price, "ev_pct": ev, "anchor": "pinnacle", "fair_odds": 1.616, "commission": comm}


def test_parse_variants():
    for text in ("/bet ae36 10 @1.65", "/bet ae36 10 @ 1.65", "/bet AE36 10 @1.65 again", "/bet ae36 10 again @1.65"):
        assert tc.parse_bet_command(text) == ("ae36", 10.0) and tc.parse_bet_price(text) == 1.65, text
    assert tc.is_bet_again("/bet ae36 10 again @1.65") and not tc.is_bet_again("/bet ae36 10 @1.65")
    assert tc.parse_bet_price("/bet ae36 10") is None and tc.parse_bet_command("/bet ae36 10") == ("ae36", 10.0)
    assert tc.parse_bet_command("/bet ae36 10 @abc") is None
    assert tc.parse_price_command("/price ae36 1.6") == ("ae36", 1.6)
    assert tc.parse_price_command("/price ae36-1 @1.6") == ("ae36-1", 1.6)
    assert tc.parse_price_command("/price ae36") is None


def test_taken_price_recomputes_edge_and_keeps_alert_values():
    _, b = bets.place_bet("ae36", 10, opp(), {}, price=1.65)
    assert b["price"] == 1.65 and b["alert_price"] == 1.71 and b["alert_ev_pct"] == 5.83
    assert abs(b["ev_pct"] - ((1.65 / (1.71 / 1.0583)) - 1) * 100) < 0.02 and 1.9 < b["ev_pct"] < 2.3
    _, b2 = bets.place_bet("ae37", 10, opp(), {}, price=1.55)
    assert b2["ev_pct"] < 0                                               # worse price -> no longer +EV
    _, b3 = bets.place_bet("ae38", 10, opp(), {})                          # no price given: untouched
    assert b3["price"] == 1.71 and "alert_price" not in b3 and b3["ev_pct"] == 5.83
    _, b4 = bets.place_bet("ae39", 10, opp(), {}, price=1.71)              # same price: untouched
    assert "alert_price" not in b4


def test_commission_is_respected():
    _, b = bets.place_bet("x1", 10, opp(price=2.0, ev=5.0, comm=0.06), {}, price=2.1)
    fair = (1 + 1.0 * 0.94) / 1.05
    assert abs(b["ev_pct"] - ((1 + 1.1 * 0.94) / fair - 1) * 100) < 0.02


def test_correcting_a_settled_bet_redoes_profit_and_clv():
    L = {}
    _, b = bets.place_bet("w1", 10, opp(price=2.0, ev=5.0), L)
    b["closing_fair_odds"] = 1.9
    bets.settle_manually(b, "won")
    assert b["profit"] == 10.0 and b["clv_pct"] == round((2.0 / 1.9 - 1) * 100, 2)
    bets.set_taken_price(b, 1.8)
    assert b["profit"] == 8.0 and b["clv_pct"] == round((1.8 / 1.9 - 1) * 100, 2) and b["status"] == "won"
    L2 = {}
    _, c = bets.place_bet("l1", 10, opp(price=2.0, ev=5.0), L2)
    bets.settle_manually(c, "lost"); bets.set_taken_price(c, 1.8)
    assert c["profit"] == -10.0


def _run(msgs, cands, ledger):
    sent = []
    with mock.patch.object(tc, "get_new_messages", return_value=msgs), \
         mock.patch.object(tc, "send_message", side_effect=sent.append):
        main.process_commands(cands, ledger)
    return sent


def test_bet_command_with_price_end_to_end():
    L, c = {}, {"c1": opp()}
    sent = _run(["/bet c1 10 @1.65"], c, L)
    (bid, b), = L.items()
    assert b["price"] == 1.65 and b["stake"] == 10 and "Price taken 1.65 (alert said 1.71)" in sent[0] and "edge now +" in sent[0]
    L, c = {}, {"c1": opp()}
    sent = _run(["/bet c1 10 @1.5"], c, L)
    assert "no longer +EV" in sent[0]
    L, c = {}, {"c1": opp()}
    sent = _run(["/bet c1 10 @0.5"], c, L)
    assert L == {} and "doesn't look right" in sent[0]
    L, c = {}, {"c1": opp()}
    sent = _run(["/bet c1 10"], c, L)
    assert L["c1"]["price"] == 1.71 and "Price taken" not in sent[0]


def test_price_command_end_to_end():
    L = {}
    bets.place_bet("a1b2", 10, opp(price=2.0, ev=5.0), L)
    sent = _run(["/price a1b2 1.9"], {}, L)
    assert L["a1b2"]["price"] == 1.9 and "2.0 → 1.9" in sent[0] and "edge now" in sent[0]
    assert "No bet with id" in _run(["/price ee99 1.9"], {}, L)[0]
    assert "doesn't look right" in _run(["/price a1b2 0.9"], {}, L)[0] and L["a1b2"]["price"] == 1.9


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
