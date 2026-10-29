"""Tests for the Pinnacle sharp-reference anchor. Run: python test_sharp.py"""
from src import config, ev_calculator as ev, telegram_alerts


def book(key, outcomes, market="h2h"):
    return {"key": key, "title": key, "markets": [{"key": market, "outcomes": outcomes}]}


def h2h(fav, dog):
    return [{"name": "Fav", "price": fav}, {"name": "Dog", "price": dog}]


def event(books, sport="tennis_x"):
    return {"id": "e1", "sport_key": sport, "commence_time": "2026-10-13T03:00:00Z",
            "home_team": "Fav", "away_team": "Dog", "bookmakers": books}


SOFT = [book(k, h2h(1.22, 4.5)) for k in ("tab", "ladbrokes_au", "neds", "unibet")]


def dog_alerts(books):
    return [o for o in ev.find_positive_ev(event(books)) if o["outcome"] == "Dog"]


def test_pinnacle_overrides_soft_consensus():
    # Soft books alone make Betfair's dog 6.0 look like value; Pinnacle (sharp, ~2% margin)
    # says the dog's true odds are ~5.3, so there is no edge.
    bf = book("betfair_ex_au", h2h(1.2, 5.2))
    pin = book("pinnacle", h2h(1.19, 5.3))
    assert dog_alerts(SOFT + [bf, pin]) == []


def test_pinnacle_anchor_flags_real_edge_and_is_labelled():
    bf = book("betfair_ex_au", h2h(1.2, 6.9))
    pin = book("pinnacle", h2h(1.19, 5.3))
    out = dog_alerts(SOFT + [bf, pin])
    assert len(out) == 1 and out[0]["anchor"] == "pinnacle" and out[0]["num_books"] == 1, out
    assert "Pinnacle no-vig line" in ev.describe_anchor(out[0])
    assert "Pinnacle no-vig line" in telegram_alerts.format_message(out[0], "ab12")


def test_falls_back_to_retail_consensus_without_pinnacle():
    bf = book("betfair_ex_au", h2h(1.2, 6.0))
    out = dog_alerts(SOFT + [bf])
    assert len(out) == 1 and out[0]["anchor"] == "retail_consensus" and out[0]["num_books"] == 4
    assert "retail consensus, 4 books" in ev.describe_anchor(out[0])


def test_pinnacle_alone_is_enough_but_consensus_alone_needs_min_books():
    bf = book("betfair_ex_au", h2h(1.2, 6.9))
    pin = book("pinnacle", h2h(1.19, 5.3))
    assert len(dog_alerts([bf, pin])) == 1                    # no soft books at all
    assert dog_alerts([bf] + SOFT[:2]) == []                  # only 2 soft books, no Pinnacle


def test_exchanges_never_feed_the_consensus():
    bf = book("betfair_ex_au", h2h(1.2, 6.0))
    ex = [book("betfair_ex_eu", h2h(1.2, 6.0)), book("matchbook", h2h(1.2, 6.0))]
    books = [bf] + SOFT[:2] + ex
    prices, _ = ev._extract_book_prices(event(books), "h2h")
    _, n_ref = ev._reference_consensus(prices)
    assert n_ref == 2                                          # exchanges not counted
    assert dog_alerts(books) == []                             # 2 < MIN_BOOKS and no sharp


def test_closing_fair_odds_use_pinnacle_when_present():
    pin = book("pinnacle", h2h(1.19, 5.3))
    odds = ev.get_reference_fair_odds(event(SOFT + [pin]), "Dog")
    assert odds is not None and 5.5 < odds < 6.0, odds
    assert ev.get_reference_fair_odds(event(SOFT[:2]), "Dog") is None   # too few books, no sharp


def test_totals_line_not_quoted_by_pinnacle_keeps_consensus_fallback():
    def tot(point, over, under):
        return [{"name": "Over", "price": over, "point": point}, {"name": "Under", "price": under, "point": point}]
    soft = [book(k, tot(2.5, 1.95, 1.9), "totals") for k in ("tab", "ladbrokes_au", "neds", "unibet")]
    pin = book("pinnacle", tot(2.75, 1.9, 2.0), "totals")          # different line
    sb = book("sportsbet", tot(2.5, 2.3, 1.6), "totals")
    out = ev.find_positive_ev(event(soft + [pin, sb], sport="soccer_epl"))
    assert any(o["outcome"] == "Over 2.5" and o["anchor"] == "retail_consensus" for o in out), out


def test_regions_include_eu_only_when_enabled():
    assert config.get_regions_for_sport("tennis_atp_shanghai_masters") == "au,eu"
    assert config.get_regions_for_sport("soccer_epl") == "au,eu"
    assert config.get_regions_for_sport("americanfootball_nfl") == "au,eu"   # NFL dropped the us region
    assert config.get_regions_for_sport("basketball_nba") == "au,us,eu"
    old = config.USE_SHARP_REFERENCE
    config.USE_SHARP_REFERENCE = False
    try:
        assert config.get_regions_for_sport("basketball_nba") == "au,us"
        assert config.get_regions_for_sport("tennis_atp_shanghai_masters") == "au"
    finally:
        config.USE_SHARP_REFERENCE = old


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
