"""Log a bet as placed at NextBet (or another book) instead of the alerted one:
/bet <id> <stake> [@price] on nextbet. Run: python test_nextbet.py"""
from datetime import datetime, timezone
from unittest import mock

from src import bets, config, daily_digest, telegram_commands as tc
import main

T = "2099-01-01T00:00:00Z"


def opp(price=2.20, ev=6.0, comm=0.0, book="SportsBet", key="sportsbet"):
    return {"event_id": "e1", "sport_key": "basketball_nba", "commence_time": T, "home_team": "H", "away_team": "A",
            "market_key": "h2h", "bookmaker_key": key, "bookmaker_title": book, "outcome": "H",
            "price": price, "ev_pct": ev, "anchor": "pinnacle", "fair_odds": 2.08, "commission": comm}


def _run(msgs, cands, ledger):
    sent = []
    with mock.patch.object(tc, "get_new_messages", return_value=msgs), \
         mock.patch.object(tc, "send_message", side_effect=sent.append):
        main.process_commands(cands, ledger)
    return sent


def test_parse_book():
    for text, book in (("/bet ab12 10 on nextbet", "nextbet"), ("/bet ab12 10 @2.3 on NextBet", "nextbet"),
                       ("/bet ab12 10 on next.bet @2.3", "next.bet"), ("/bet ab12 10 again on nb", "nb"),
                       ("/bet ab12 10", None), ("/bet ab12 10 @2.3", None)):
        assert tc.parse_bet_book(text) == book, text
        assert tc.parse_bet_command(text) == ("ab12", 10.0), text
    assert tc.parse_bet_price("/bet ab12 10 @2.3 on nextbet") == 2.3
    assert tc.is_bet_again("/bet ab12 10 again on nextbet")
    assert tc.parse_bet_command("/bet ab12 10 on") is None


def test_alert_from_sportsbet_placed_at_nextbet_with_own_price():
    L, c = {}, {"ab12": opp()}
    sent = _run(["/bet ab12 10 @2.30 on nextbet"], c, L)
    b = L["ab12"]
    assert b["bookmaker_title"] == "NextBet" and b["bookmaker_key"] == "nextbet" and b["commission"] == 0.0
    assert b["alert_bookmaker_title"] == "SportsBet" and b["price"] == 2.3 and b["alert_price"] == 2.2
    assert b["ev_pct"] > 6.0                                                 # better price than the alert's
    assert "at NextBet" in sent[0] and "Placed at NextBet (alert was for SportsBet)" in sent[0]
    # it shows as NextBet in the open list and in /breakdown book
    assert "on NextBet" in daily_digest.open_bets_text(L, datetime(2098, 12, 31, tzinfo=timezone.utc))
    from src import breakdown
    L["ab12"]["status"], L["ab12"]["profit"] = "won", 13.0
    assert "NextBet: 1-0" in breakdown.build(L, "book")


def test_betfair_alert_placed_at_nextbet_drops_the_commission():
    o = opp(price=2.20, ev=6.0, comm=0.06, book="Betfair", key="betfair_ex_au")
    _, b = bets.place_bet("bf01", 10, o, {}, book=("nextbet", "NextBet", 0.0))
    assert b["commission"] == 0.0 and b["alert_bookmaker_title"] == "Betfair"
    fair = (1 + 1.2 * 0.94) / 1.06
    assert abs(b["ev_pct"] - (2.20 / fair - 1) * 100) < 0.02 and b["ev_pct"] > 6.0   # no commission -> bigger edge
    # and the reverse: a SportsBet alert placed on Betfair picks up the sport's commission
    o2 = opp()
    _, b2 = bets.place_bet("sb01", 10, o2, {}, book=("betfair_ex_au", "Betfair", 0.06))
    assert b2["commission"] == 0.06 and b2["ev_pct"] < 6.0


def test_no_book_means_unchanged_and_unknown_book_is_rejected():
    L, c = {}, {"ab12": opp()}
    _run(["/bet ab12 10"], c, L)
    assert L["ab12"]["bookmaker_title"] == "SportsBet" and "alert_bookmaker_title" not in L["ab12"]
    L, c = {}, {"ab12": opp()}
    sent = _run(["/bet ab12 10 on bet365"], c, L)
    assert L == {} and "Don't know the book 'bet365'" in sent[0] and "NextBet" in sent[0]


def test_duplicate_guard_still_catches_a_bet_placed_at_another_book():
    L, c = {}, {"ab12": opp()}
    _run(["/bet ab12 10 on nextbet"], c, L)
    sent = _run(["/bet ab12 10"], c, L)                     # same alert logged again
    assert len(L) == 1 and "Already logged" in sent[0]
    _run(["/bet ab12 10 again on nextbet"], c, L)           # deliberately a second one
    assert len(L) == 2


def test_playup_feed_prices_are_nextbet():
    """The feed's 'playup' book is NextBet: it alerts as NextBet, and is kept out of the consensus."""
    from src import ev_calculator as ev
    from datetime import timedelta

    def bk(key, a, b):
        return {"key": key, "title": key.title(), "markets": [{"key": "h2h", "outcomes": [
            {"name": "Alpha", "price": a}, {"name": "Beta", "price": b}]}]}
    soft = [bk(k, 1.90, 1.95) for k in ("tab", "ladbrokes_au", "neds", "unibet", "pointsbetau")]
    t = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    e = {"id": "e9", "sport_key": "tennis_atp_x", "commence_time": t, "home_team": "Alpha", "away_team": "Beta",
         "bookmakers": soft + [{"key": "playup", "title": "PlayUp", "markets": [{"key": "h2h", "outcomes": [
             {"name": "Alpha", "price": 2.20}, {"name": "Beta", "price": 1.70}]}]}]}
    prices, titles = ev._extract_book_prices(e, "h2h")
    assert "playup" not in prices and titles["nextbet"] == "NextBet" and prices["nextbet"]["Alpha"] == 2.20
    assert "nextbet" in config.BETTABLE_BOOKS
    opps = ev.find_positive_ev(e)
    mine = [o for o in opps if o["bookmaker_key"] == "nextbet"]
    assert mine and mine[0]["bookmaker_title"] == "NextBet" and mine[0]["commission"] == 0.0 and mine[0]["outcome"] == "Alpha"
    # NextBet's own price is not part of the consensus it is checked against
    cons, _ = ev._reference_consensus(prices)
    soft_only, _ = ev._reference_consensus({k: v for k, v in prices.items() if k != "nextbet"})
    assert cons == soft_only
    # and /bet ... on playup resolves to NextBet
    assert config.PLACEABLE_BOOKS["playup"] == ("nextbet", "NextBet")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
