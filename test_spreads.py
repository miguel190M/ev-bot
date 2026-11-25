"""Handicap (spreads) betting: settlement, opposing-side rule, arbitrage hedge, alerts.
Run: python test_spreads.py"""
from datetime import datetime, timedelta, timezone

from src import bets, config, ev_calculator as ev

T = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat().replace("+00:00", "Z")


def sp(book, home_pt, h_price, a_price, home="Boston Celtics", away="LA Lakers"):
    return {"key": book, "title": book.title(), "markets": [{"key": "spreads", "outcomes": [
        {"name": home, "price": h_price, "point": home_pt},
        {"name": away, "price": a_price, "point": -home_pt}]}]}


def event(books, home="Boston Celtics", away="LA Lakers", sport="basketball_nba"):
    return {"id": "e1", "sport_key": sport, "commence_time": T, "home_team": home, "away_team": away,
            "bookmakers": books}


def bet(outcome, market="spreads", home="Boston Celtics", away="LA Lakers", price=2.0, stake=10.0):
    return {"status": "open", "sport_key": "basketball_nba", "event_id": "e1", "commence_time": T,
            "home_team": home, "away_team": away, "outcome": outcome, "price": price, "stake": stake,
            "commission": 0.0, "market_key": market, "profit": None, "bookmaker_title": "SportsBet"}


def settle(outcome, home_score, away_score, **kw):
    b = bet(outcome, **kw)
    assert bets.resolve_bet(b, {kw.get("home", "Boston Celtics"): home_score, kw.get("away", "LA Lakers"): away_score})
    return b


def test_settlement():
    assert settle("Boston Celtics -5.5", 110, 104)["status"] == "won"        # wins by 6, covers
    assert settle("Boston Celtics -5.5", 110, 105)["status"] == "lost"       # wins by 5, doesn't cover
    assert settle("LA Lakers 5.5", 110, 104)["status"] == "lost"             # away team loses by 6
    assert settle("LA Lakers 5.5", 104, 110)["status"] == "won"              # away team wins outright
    b = settle("LA Lakers 5.5", 110, 105)                                    # loses by 5, covers
    assert b["status"] == "won" and b["profit"] == 10.0
    assert settle("LA Lakers -2.5", 100, 110)["status"] == "won"             # road favourite
    b = settle("Boston Celtics -4", 110, 106)                                # lands exactly on the line
    assert b["status"] == "void" and b["profit"] == 0.0
    b = settle("Philadelphia 76ers -3.5", 100, 90, home="Philadelphia 76ers", away="Miami Heat")
    assert b["status"] == "won"                                              # team name with digits
    b = settle("Boston Celtics -5.5", 110, 104)
    assert b["status"] == "won" and b["profit"] == 10.0
    # totals and h2h still settle as before
    assert settle("Over 200.5", 110, 104, market="totals")["status"] == "won"
    assert settle("Boston Celtics", 110, 104, market="h2h")["status"] == "won"


def test_is_opposing_mirrored_line_only():
    held = bet("Boston Celtics -5.5")
    mk = lambda o: {"event_id": "e1", "market_key": "spreads", "outcome": o}
    assert bets.is_opposing(mk("LA Lakers 5.5"), held)                        # the other side
    assert not bets.is_opposing(mk("LA Lakers 6.5"), held)                    # different line: not a hedge
    assert not bets.is_opposing(mk("Boston Celtics -6.5"), held)              # same team, other line
    assert not bets.is_opposing(mk("Boston Celtics -5.5"), held)              # identical bet
    assert not bets.is_opposing({"event_id": "e1", "market_key": "h2h", "outcome": "LA Lakers"}, held)  # other market


def test_positive_ev_alert_on_spreads():
    soft = [sp(k, -5.5, 1.91, 1.91) for k in ("pinnacle", "tab", "neds", "unibet", "ladbrokes_au")]
    opps = ev.find_positive_ev(event(soft + [sp("sportsbet", -5.5, 2.15, 1.72)]))
    mine = [o for o in opps if o["market_key"] == "spreads"]
    assert mine and mine[0]["outcome"] == "Boston Celtics -5.5" and mine[0]["bookmaker_key"] == "sportsbet"
    assert mine[0]["anchor"] == "pinnacle" and mine[0]["ev_pct"] > 5
    # a bettable book on a DIFFERENT line from Pinnacle is not compared with it
    off = ev.find_positive_ev(event(soft + [sp("sportsbet", -6.5, 2.15, 1.72)]))
    assert not [o for o in off if o["bookmaker_key"] == "sportsbet" and o["market_key"] == "spreads"]


def test_hedge_arb_at_mirrored_line():
    held = [("a1", bet("Boston Celtics -5.5", price=2.10, stake=20.0))]
    books = [sp("sportsbet", -5.5, 2.05, 1.75), sp("betfair_ex_au", -5.5, 1.95, 2.30),
             sp("tab", -6.5, 1.95, 1.85)]                                     # tab quotes another line: ignored
    arbs = ev.find_hedge_arbs(event(books), held)
    assert len(arbs) == 1
    o, a = arbs[0], arbs[0]["arb"]
    assert o["market_key"] == "spreads" and o["outcome"] == "LA Lakers 5.5" and o["bookmaker_key"] == "betfair_ex_au"
    eff_b = 1 + 1.30 * 0.94
    assert abs(a["stake"] - round(20 * 2.10 / eff_b, 2)) < 0.011 and a["profit_pct"] >= config.ARB_MIN_PROFIT_PCT
    # no hedge when the other side's price doesn't make an arb
    assert ev.find_hedge_arbs(event([sp("betfair_ex_au", -5.5, 1.95, 1.90)]), held) == []
    # and no mirror at all at that line -> nothing
    assert ev.find_hedge_arbs(event([sp("betfair_ex_au", -6.5, 1.95, 2.30)]), held) == []


def test_markets_config():
    for k, cost in (("basketball_nba", 9), ("americanfootball_nfl", 6)):
        assert config.get_markets_for_sport(k) == "h2h,totals,spreads"
        assert len(config.get_regions_for_sport(k).split(",")) * 3 == cost
    for k in ("aussierules_afl", "rugbyleague_nrl"):
        assert config.get_markets_for_sport(k) == "h2h,totals"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
