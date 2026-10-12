"""
+EV detection for a set of bettable bookmakers: every OTHER bookmaker acts
purely as the reference market, and only prices from config.BETTABLE_BOOKS
are ever evaluated or alerted on.

This generalizes the earlier Betfair-only design to any number of books you
can actually place bets through (e.g. Betfair Exchange AND Sportsbet). The
reasoning is the same either way: a bettable book's own price can't be
compared to a "fair line" that already includes it, so all bettable books
are excluded from the consensus - only the remaining, non-bettable books
build the fair-value line that gets checked against.

Multiple markets: an event can carry more than one market (h2h, and totals
for sports configured in config.SPORT_MARKET_OVERRIDES). Each market is
evaluated completely independently - a moneyline fair line and a totals
fair line are unrelated bets, so mixing them into one consensus would be
meaningless. Outcomes within a market are identified by name AND line where
a line exists (e.g. "Over 224.5"), since different books quoting "Over" at
different points are not the same bet - comparing them directly would
silently compare unrelated wagers. The practical effect: totals alerts will
fire less often than moneyline ones, since fewer books tend to agree on the
exact same line. That's correct, careful behavior, not a bug.

Commission: Betfair charges commission on NET WINNINGS only (see
config.get_commission_rate). The EV% here is always calculated on the
commission-adjusted payout, not the raw quoted price - a bet that looks
like a solid edge on Betfair's displayed odds can be barely breakeven once
its cut comes out, especially on NRL's much higher rate. `price` in the
resulting opportunity is still the RAW quoted price (what you'll actually
see and click), so the two are reported side by side rather than one
silently overwriting the other.

EV% = (commission-adjusted payout on a bettable book's price x
       fair probability) - 1
where the fair probability is the sharp book's (Pinnacle) de-vigged line when
it quotes the outcome, else the retail median consensus - see _fair_probabilities.
"""

import statistics

from . import config


def _power_devig(implied: dict[str, float]) -> dict[str, float]:
    """Power-method de-vig: find the exponent c > 1 such that sum(q_i ** c) == 1
    and return q_i ** c. Unlike simple proportional scaling, this takes MORE
    margin off long shots than favourites - which is where bookmakers
    actually hide it (the favourite-longshot bias). Proportional scaling
    leaves long shots' fair probability too high, so their fair odds look too
    short and a low-margin price (e.g. Betfair) on a long shot looks like
    value when it isn't. Falls back to proportional scaling if there is no
    overround to remove or any implied probability is >= 1 (degenerate)."""
    total = sum(implied.values())
    if total <= 1.0 or any(q >= 1.0 for q in implied.values()):
        return {k: q / total for k, q in implied.items()}
    lo, hi = 1.0, 20.0  # sum(q**c) is strictly decreasing in c; root lies inside
    for _ in range(100):
        mid = (lo + hi) / 2
        if sum(q ** mid for q in implied.values()) > 1.0:
            lo = mid
        else:
            hi = mid
    c = (lo + hi) / 2
    probs = {k: q ** c for k, q in implied.items()}
    norm = sum(probs.values())  # ~1.0; guards residual bisection error
    return {k: p / norm for k, p in probs.items()}


def _shin_devig(implied: dict[str, float]) -> dict[str, float]:
    """Shin's method: models the overround as protection against a fraction z
    of insider money and solves for z so the fair probabilities sum to 1:
        p_i = (sqrt(z^2 + 4(1-z) q_i^2 / sum(q)) - z) / (2(1-z))
    Like the power method it takes more margin off long shots than favourites
    (the favourite-longshot bias), but it is the standard published method
    and less aggressive than power on very lopsided markets. Falls back to
    proportional scaling when there is no overround to remove or any implied
    probability is >= 1."""
    total = sum(implied.values())
    if total <= 1.0 or any(q >= 1.0 for q in implied.values()):
        return {k: q / total for k, q in implied.items()}

    def probs(z: float) -> dict[str, float]:
        return {k: (((z * z + 4 * (1 - z) * q * q / total) ** 0.5) - z) / (2 * (1 - z))
                for k, q in implied.items()}

    lo, hi = 0.0, 0.5   # sum(probs(z)) falls as z rises; root lies inside
    for _ in range(100):
        mid = (lo + hi) / 2
        if sum(probs(mid).values()) > 1.0:
            lo = mid
        else:
            hi = mid
    out = probs((lo + hi) / 2)
    norm = sum(out.values())
    return {k: p / norm for k, p in out.items()}


def devig_probabilities(outcomes: list[dict]) -> dict[str, float]:
    """Given one bookmaker's outcomes [{name, price, point?}, ...], return
    de-vigged (margin-free) probabilities keyed by outcome identity (see
    _outcome_key). Method set by config.DEVIG_METHOD: "shin" (default),
    "power" (most aggressive on long shots) or "multiplicative" (legacy,
    scales every outcome equally - overstates long shots)."""
    implied = {_outcome_key(o): 1.0 / o["price"] for o in outcomes if o.get("price")}
    total = sum(implied.values())
    if total <= 0:
        return {}
    if config.DEVIG_METHOD == "multiplicative":
        return {key: p / total for key, p in implied.items()}
    if config.DEVIG_METHOD == "power":
        return _power_devig(implied)
    return _shin_devig(implied)


def _outcome_key(outcome: dict) -> str:
    """Identity for one outcome within a market. For h2h this is just the
    team/selection name. For totals (and spreads, if ever added), the same
    name ("Over"/"Under") can refer to completely different bets depending
    on the line, so the line is folded into the key - two books' "Over"
    only count as the same outcome if they're quoting the exact same
    point. Stricter than name-matching alone, but the alternative
    (treating Over 224.5 and Over 227.5 as interchangeable) would silently
    compare unrelated bets."""
    point = outcome.get("point")
    return outcome["name"] if point is None else f"{outcome['name']} {point}"


def _extract_book_prices(event: dict, market_key: str) -> tuple[dict, dict]:
    """Return (book_key -> {outcome_key: price}, book_key -> title) for
    every bookmaker quoting this specific market on this event."""
    book_prices, book_titles = {}, {}
    for bm in event.get("bookmakers", []):
        market = next((m for m in bm.get("markets", []) if m["key"] == market_key), None)
        if not market:
            continue
        outcomes = market.get("outcomes", [])
        if len(outcomes) < 2:
            continue
        book_prices[bm["key"]] = {_outcome_key(o): o["price"] for o in outcomes}
        book_titles[bm["key"]] = bm.get("title", bm["key"])
    return book_prices, book_titles


def _reference_consensus(book_prices: dict) -> tuple[dict, int]:
    """De-vig every non-bettable book and return the MEDIAN probability per
    outcome across all of them. No leave-one-out needed here - none of
    these books are being individually evaluated, they're all just
    contributing to one shared consensus line that the bettable books get
    checked against."""
    reference_devig = {
        k: devig_probabilities([{"name": n, "price": p} for n, p in v.items()])
        for k, v in book_prices.items()
        if k not in config.BETTABLE_BOOKS and k not in config.REFERENCE_EXCLUDE_BOOKS
    }
    outcome_keys = set()
    for probs in reference_devig.values():
        outcome_keys.update(probs.keys())

    consensus = {}
    for key in outcome_keys:
        probs = [d[key] for d in reference_devig.values() if key in d]
        if probs:
            consensus[key] = statistics.median(probs)
    return consensus, len(reference_devig)


def _sharp_probabilities(book_prices: dict) -> tuple[str | None, dict]:
    """De-vigged probabilities from the first available sharp reference book
    (config.SHARP_REFERENCE_BOOKS, i.e. Pinnacle), or (None, {})."""
    if not config.USE_SHARP_REFERENCE:
        return None, {}
    for book_key in config.SHARP_REFERENCE_BOOKS:
        prices = book_prices.get(book_key)
        if prices and len(prices) >= 2:
            return book_key, devig_probabilities([{"name": n, "price": p} for n, p in prices.items()])
    return None, {}


def _fair_probabilities(book_prices: dict) -> dict[str, tuple[float, str, int]]:
    """outcome -> (fair probability, anchor label, number of reference books).
    Base layer is the retail median consensus (needs MIN_BOOKS non-bettable
    books). Where the sharp book quotes an outcome, its de-vigged line
    OVERRIDES the consensus for that outcome - a single sharp book is
    trusted over many soft ones, so MIN_BOOKS isn't required for it. An
    outcome the sharp book doesn't quote (e.g. a different totals line) keeps
    the consensus value if there is one."""
    fair = {}
    consensus, n_ref = _reference_consensus(book_prices)
    if n_ref >= config.MIN_BOOKS:
        for key, prob in consensus.items():
            fair[key] = (prob, "retail_consensus", n_ref)
    sharp_key, sharp = _sharp_probabilities(book_prices)
    for key, prob in sharp.items():
        fair[key] = (prob, sharp_key, 1)
    return fair


def describe_anchor(opp: dict) -> str:
    """Human label for where an opportunity's fair price came from."""
    anchor = opp.get("anchor", "retail_consensus")
    if anchor == "retail_consensus":
        return f"retail consensus, {opp.get('num_books', '?')} books"
    return f"{anchor.title()} no-vig line"


def _effective_price(price: float, commission: float) -> float:
    """Decimal price after commission on net winnings. Only the profit
    portion is taxed - your stake back is untouched - so it's 1 (stake
    returned) plus the winnings reduced by the commission rate, not the
    whole price scaled down."""
    return 1 + (price - 1) * (1 - commission)


def _make_opportunity(event, market_key, book_key, book_title, price, outcome, fair_prob, num_books, commission, ev,
                      anchor="retail_consensus"):
    return {
        "event_id": event["id"],
        "sport_key": event["sport_key"],
        "commence_time": event["commence_time"],
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
        "market_key": market_key,  # "h2h", "totals", etc - needed to resolve the bet correctly later
        "bookmaker_key": book_key,
        "bookmaker_title": book_title,
        "outcome": outcome,  # e.g. "Lakers" for h2h, "Over 224.5" for totals
        "price": price,  # raw quoted price - what you'll actually see and click
        "commission": commission,  # 0.0 for books that don't charge one (e.g. Sportsbet)
        "fair_probability": round(fair_prob, 4),
        "fair_odds": round(1 / fair_prob, 3),
        "ev_pct": round(ev * 100, 2),  # already commission-adjusted
        "anchor": anchor,  # "retail_consensus" or the sharp book key (e.g. "pinnacle")
        "num_books": num_books,
    }


def get_reference_fair_odds(event: dict, outcome: str, market_key: str = "h2h") -> float | None:
    """Fair odds for one specific outcome from the current reference
    consensus in the given market - independent of any bettable book's own
    price. Used for CLV tracking: called each time an open bet's event
    gets re-scanned as kickoff approaches, so the last value captured
    before the game starts becomes the closing-line proxy. Returns None if
    there aren't enough reference books to trust the consensus, or the
    outcome isn't quoted."""
    book_prices, _ = _extract_book_prices(event, market_key)
    entry = _fair_probabilities(book_prices).get(outcome)
    if not entry or not entry[0]:
        return None
    return round(1 / entry[0], 3)


def _find_positive_ev_for_market(event: dict, market_key: str) -> list[dict]:
    """Same logic as find_positive_ev, scoped to one specific market."""
    opportunities = []
    book_prices, book_titles = _extract_book_prices(event, market_key)

    bettable_present = {k: v for k, v in book_prices.items() if k in config.BETTABLE_BOOKS}
    if not bettable_present:
        return opportunities  # none of your bettable books are quoting this market

    fair = _fair_probabilities(book_prices)
    if not fair:
        return opportunities  # no sharp line and not enough reference books to trust a consensus

    for book_key, prices in bettable_present.items():
        commission = config.get_commission_rate(book_key, event["sport_key"])
        for outcome, price in prices.items():
            entry = fair.get(outcome)
            if not entry or not price:
                continue
            fair_prob, anchor, num_ref = entry
            effective_price = _effective_price(price, commission)
            ev = effective_price * fair_prob - 1
            if ev * 100 > config.MAX_EV_PCT:
                print(f"    suppressed {book_key} {outcome} @ {price}: {ev * 100:.1f}% edge exceeds "
                      f"MAX_EV_PCT={config.MAX_EV_PCT:g} (likely stale/bad price)")
                continue
            if ev >= config.get_ev_threshold(price):
                opportunities.append(_make_opportunity(
                    event, market_key, book_key, book_titles[book_key], price, outcome, fair_prob,
                    num_ref, commission, ev, anchor=anchor,
                ))
    return opportunities


def find_positive_ev(event: dict) -> list[dict]:
    """Scan a single event across every market present (h2h, and totals for
    sports where that's configured) for +EV prices on any bettable book.
    Each market is evaluated completely independently - see module
    docstring. Nothing is ever flagged for a book outside
    config.BETTABLE_BOOKS."""
    market_keys = set()
    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            market_keys.add(m["key"])

    opportunities = []
    for market_key in market_keys:
        opportunities.extend(_find_positive_ev_for_market(event, market_key))
    return opportunities
