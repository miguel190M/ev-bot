"""Tests for the power-method de-vig. Run: python test_devig.py"""
from src import config, ev_calculator as ev


def _probs(prices, method=None):
    old = config.DEVIG_METHOD
    if method:
        config.DEVIG_METHOD = method
    try:
        return ev.devig_probabilities([{"name": f"o{i}", "price": p} for i, p in enumerate(prices)])
    finally:
        config.DEVIG_METHOD = old


def test_probabilities_sum_to_one():
    for prices in ([1.22, 4.5], [2.0, 2.0], [1.9, 3.6, 4.2], [1.05, 12.0], [1.5, 2.6]):
        p = _probs(prices)
        assert abs(sum(p.values()) - 1) < 1e-9, (prices, p)


def test_power_takes_more_margin_off_longshots_than_multiplicative():
    pw, mu = _probs([1.22, 4.5], "power"), _probs([1.22, 4.5], "multiplicative")
    assert pw["o1"] < mu["o1"]           # longshot prob lower under power
    assert pw["o0"] > mu["o0"]           # favourite prob higher
    assert round(1 / pw["o1"], 2) == 5.14 and round(1 / mu["o1"], 2) == 4.69


def test_shin_sits_between_multiplicative_and_power_on_longshots():
    mu, sh, pw = (_probs([1.22, 4.5], m)["o1"] for m in ("multiplicative", "shin", "power"))
    assert pw < sh < mu
    assert round(1 / sh, 2) == 4.97
    assert config.DEVIG_METHOD == "shin"          # default


def test_even_market_identical_under_all_methods():
    for m in ("power", "multiplicative", "shin"):
        assert abs(_probs([1.9, 1.9], m)["o0"] - 0.5) < 1e-9


def test_three_way_and_degenerate_inputs():
    assert abs(sum(_probs([2.1, 3.4, 3.6]).values()) - 1) < 1e-9
    for m in ("shin", "power"):
        p = _probs([1.0, 5.0], m)        # implied 1.0 -> falls back, no crash
        assert abs(sum(p.values()) - 1) < 1e-9
        p = _probs([2.2, 2.2], m)        # no overround (sum<1) -> proportional
        assert abs(p["o0"] - 0.5) < 1e-9


def test_longshot_no_longer_flagged_when_only_margin_bias():
    """Soft books quote fav 1.22 / dog 4.5 (~4% overround). Betfair offers the
    dog at 5.5 (6% commission). Proportional scaling calls that value; shin
    does not."""
    def event(dog_price):
        books = []
        for k in ("tab", "ladbrokes_au", "neds", "unibet"):
            books.append({"key": k, "title": k, "markets": [{"key": "h2h", "outcomes": [
                {"name": "Fav", "price": 1.22}, {"name": "Dog", "price": 4.5}]}]})
        books.append({"key": "betfair_ex_au", "title": "Betfair", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Fav", "price": 1.2}, {"name": "Dog", "price": dog_price}]}]})
        return {"id": "e", "sport_key": "tennis_x", "commence_time": "2026-10-13T00:00:00Z",
                "home_team": "Fav", "away_team": "Dog", "bookmakers": books}
    old = config.DEVIG_METHOD
    try:
        config.DEVIG_METHOD = "multiplicative"
        legacy = [o for o in ev.find_positive_ev(event(5.5)) if o["outcome"] == "Dog"]
        config.DEVIG_METHOD = "shin"
        new = [o for o in ev.find_positive_ev(event(5.5)) if o["outcome"] == "Dog"]
    finally:
        config.DEVIG_METHOD = old
    assert legacy and not new, (legacy, new)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
