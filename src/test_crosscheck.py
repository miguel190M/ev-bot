"""Tests for the Pinnacle vs soft-book cross-check. Run: python test_crosscheck.py"""
from src import config, ev_calculator as ev, telegram_alerts


def book(key, outcomes):
    return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": outcomes}]}


def h2h(fav, dog):
    return [{"name": "Fav", "price": fav}, {"name": "Dog", "price": dog}]


def event(books):
    return {"id": "e1", "sport_key": "tennis_x", "commence_time": "2026-10-13T03:00:00Z",
            "home_team": "Fav", "away_team": "Dog", "bookmakers": books}


def soft(fav, dog):
    return [book(k, h2h(fav, dog)) for k in ("tab", "ladbrokes_au", "neds", "unibet")]


def dog(books):
    return [o for o in ev.find_positive_ev(event(books)) if o["outcome"] == "Dog"]


def test_agreement_uses_pinnacle_and_is_not_flagged():
    out = dog(soft(1.22, 4.5) + [book("pinnacle", h2h(1.21, 4.6)), book("betfair_ex_au", h2h(1.2, 6.0))])
    assert len(out) == 1 and out[0]["anchor"] == "pinnacle" and out[0]["sharp_disagreement"] is False
    assert out[0]["fair_probability"] == out[0]["sharp_probability"]
    assert "disagree" not in ev.describe_anchor(out[0])


def test_pinnacle_optimistic_vs_consensus_suppresses_the_bet():
    # Pinnacle alone says Betfair 6.0 is value; soft books (dog 6.0) say it isn't.
    books = soft(1.15, 6.0) + [book("pinnacle", h2h(1.22, 4.5)), book("betfair_ex_au", h2h(1.2, 6.0))]
    old = config.SHARP_DISAGREE_PCT
    config.SHARP_DISAGREE_PCT = 1e9                 # cross-check effectively off
    try:
        assert len(dog(books)) == 1, "Pinnacle alone should alert here"
    finally:
        config.SHARP_DISAGREE_PCT = old
    assert dog(books) == []                          # cross-check on: must survive both


def test_pinnacle_pessimistic_still_alerts_flagged_with_both_numbers():
    books = soft(1.22, 4.0) + [book("pinnacle", h2h(1.19, 5.3)), book("betfair_ex_au", h2h(1.2, 6.9))]
    out = dog(books)
    assert len(out) == 1 and out[0]["sharp_disagreement"] is True
    assert out[0]["fair_probability"] == out[0]["sharp_probability"] < out[0]["consensus_probability"]
    assert "books disagree" in ev.describe_anchor(out[0])
    msg = telegram_alerts.format_message(out[0], "ab12")
    assert "⚠️ Low confidence" in msg and "Pinnacle fair ~" in msg and "soft-book median ~" in msg


def test_no_consensus_means_no_flag():
    out = dog(soft(1.22, 4.5)[:2] + [book("pinnacle", h2h(1.19, 5.3)), book("betfair_ex_au", h2h(1.2, 6.9))])
    assert len(out) == 1 and out[0]["sharp_disagreement"] is False and out[0]["consensus_probability"] is None


def test_closing_fair_odds_stay_pure_pinnacle_even_when_books_disagree():
    books = soft(1.15, 6.0) + [book("pinnacle", h2h(1.22, 4.5))]
    odds = ev.get_reference_fair_odds(event(books), "Dog")
    pin_only = ev.get_reference_fair_odds(event([book("pinnacle", h2h(1.22, 4.5))]), "Dog")
    assert odds == pin_only


def test_bet_record_keeps_the_flag():
    from src import bets
    opp = {"event_id": "e1", "sport_key": "tennis_x", "commence_time": "2026-10-13T03:00:00Z",
           "home_team": "Fav", "away_team": "Dog", "bookmaker_title": "Betfair", "outcome": "Dog",
           "price": 6.9, "ev_pct": 12.0, "anchor": "pinnacle", "sharp_disagreement": True,
           "alerted_at": "2026-10-12T05:00:00+00:00"}
    _, bet = bets.place_bet("ab12", 5.0, opp, {})
    assert bet["sharp_disagreement"] is True


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
