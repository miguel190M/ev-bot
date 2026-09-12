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
       reference-consensus fair probability) - 1
"""

import statistics

from . import config


def devig_probabilities(outcomes: list[dict]) -> dict[str, float]:
    """Given one bookmaker's outcomes [{name, price, point?}, ...], return
    de-vigged (margin-free) probabilities keyed by outcome identity (see
    _outcome_key)."""
    implied = {_outcome_key(o): 1.0 / o["price"] for o in outcomes if o.get("price")}
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {key: p / total for key, p in implied.items()}


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
        for k, v in book_prices.items() if k not in config.BETTABLE_BOOKS
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


def _effective_price(price: float, commission: float) -> float:
    """Decimal price after commission on net winnings. Only the profit
    portion is taxed - your stake back is untouched - so it's 1 (stake
    returned) plus the winnings reduced by the commission rate, not the
    whole price scaled down."""
    return 1 + (price - 1) * (1 - commission)


def _make_opportunity(event, market_key, book_key, book_title, price, outcome, fair_prob, num_books, commission, ev):
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
        "anchor": "retail_consensus",
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
    fair_probs, num_reference_books = _reference_consensus(book_prices)
    if num_reference_books < config.MIN_BOOKS:
        return None
    fair_prob = fair_probs.get(outcome)
    if not fair_prob:
        return None
    return round(1 / fair_prob, 3)


def _find_positive_ev_for_market(event: dict, market_key: str) -> list[dict]:
    """Same logic as find_positive_ev, scoped to one specific market."""
    opportunities = []
    book_prices, book_titles = _extract_book_prices(event, market_key)

    bettable_present = {k: v for k, v in book_prices.items() if k in config.BETTABLE_BOOKS}
    if not bettable_present:
        return opportunities  # none of your bettable books are quoting this market

    fair_probs, num_reference_books = _reference_consensus(book_prices)
    if num_reference_books < config.MIN_BOOKS:
        return opportunities  # not enough reference books to trust the consensus

    for book_key, prices in bettable_present.items():
        commission = config.get_commission_rate(book_key, event["sport_key"])
        for outcome, price in prices.items():
            fair_prob = fair_probs.get(outcome)
            if not fair_prob or not price:
                continue
            effective_price = _effective_price(price, commission)
            ev = effective_price * fair_prob - 1
            if ev >= config.get_ev_threshold(price):
                opportunities.append(_make_opportunity(
                    event, market_key, book_key, book_titles[book_key], price, outcome, fair_prob,
                    num_reference_books, commission, ev,
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
