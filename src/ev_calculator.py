"""
+EV detection for Betfair-only betting: retail bookmakers act purely as the
reference market, and Betfair Exchange's own back price is the only thing
ever evaluated or alerted on.

Why the flip from the original design: this tool used to treat Betfair's
back/lay spread as the sharp reference price and looked for retail books
beating it. That made sense when you might bet through any of them. Once
you're only betting through Betfair, that framing is backwards - Betfair's
own price is no longer "the outside sharp price" to compare against, it's
literally the price you'd get. So now the retail books (Sportsbet, TAB,
Neds, Ladbrokes) are de-vigged and combined into a MEDIAN consensus fair
line, and Betfair's back price is checked against that line instead.

This also means retail books' own prices are never flagged anymore - there's
nothing to act on there since you're not betting through them. An event is
only interesting if Betfair itself is offering a price better than what the
wider retail market implies is fair - which does happen, since Betfair AU
can be slower to move or thinner on some markets than the big retail books.

EV% = (Betfair's decimal odds x retail-consensus fair probability) - 1
"""

import statistics

from . import config


def devig_probabilities(outcomes: list[dict]) -> dict[str, float]:
    """Given one bookmaker's outcomes [{name, price}, ...], return de-vigged
    (margin-free) probabilities per outcome name."""
    implied = {o["name"]: 1.0 / o["price"] for o in outcomes if o.get("price")}
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {name: p / total for name, p in implied.items()}


def _extract_book_prices(event: dict) -> tuple[dict, dict]:
    """Return (book_key -> {outcome: price}, book_key -> title) for every
    bookmaker with a valid h2h market on this event."""
    book_prices, book_titles = {}, {}
    for bm in event.get("bookmakers", []):
        market = next((m for m in bm.get("markets", []) if m["key"] == config.MARKET), None)
        if not market:
            continue
        outcomes = market.get("outcomes", [])
        if len(outcomes) < 2:
            continue
        book_prices[bm["key"]] = {o["name"]: o["price"] for o in outcomes}
        book_titles[bm["key"]] = bm.get("title", bm["key"])
    return book_prices, book_titles


def _retail_consensus(book_prices: dict) -> dict[str, float]:
    """De-vig every non-Betfair book and return the MEDIAN probability per
    outcome across all of them. Unlike the old leave-one-out approach, there's
    no need to exclude any one retail book from its own evaluation here -
    none of them are being individually evaluated anymore, they're all just
    contributing to a single consensus line that only Betfair gets checked
    against. Using the full set rather than leave-one-out is a bit less
    noisy as a result."""
    retail_devig = {
        k: devig_probabilities([{"name": n, "price": p} for n, p in v.items()])
        for k, v in book_prices.items() if k != config.BETFAIR_KEY
    }
    outcome_names = set()
    for probs in retail_devig.values():
        outcome_names.update(probs.keys())

    consensus = {}
    for outcome in outcome_names:
        probs = [d[outcome] for d in retail_devig.values() if outcome in d]
        if len(probs) >= 1:
            consensus[outcome] = statistics.median(probs)
    return consensus, len(retail_devig)


def _make_opportunity(event, price, outcome, fair_prob, num_books):
    return {
        "event_id": event["id"],
        "sport_key": event["sport_key"],
        "commence_time": event["commence_time"],
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
        "bookmaker_key": config.BETFAIR_KEY,
        "bookmaker_title": "Betfair Exchange",
        "outcome": outcome,
        "price": price,
        "fair_probability": round(fair_prob, 4),
        "fair_odds": round(1 / fair_prob, 3),
        "ev_pct": round((price * fair_prob - 1) * 100, 2),
        "anchor": "retail_consensus",
        "num_books": num_books,
    }


def find_positive_ev(event: dict) -> list[dict]:
    """Scan a single event for a +EV price on Betfair, judged against the
    retail consensus. Returns a list with 0 or 1 opportunities per outcome -
    nothing is ever flagged for any book other than Betfair."""
    opportunities = []
    book_prices, _ = _extract_book_prices(event)

    betfair_prices = book_prices.get(config.BETFAIR_KEY)
    if not betfair_prices:
        return opportunities  # Betfair isn't quoting this event at all - nothing to bet

    fair_probs, num_retail_books = _retail_consensus(book_prices)
    if num_retail_books < config.MIN_BOOKS:
        return opportunities  # not enough retail books to trust the consensus

    for outcome, price in betfair_prices.items():
        fair_prob = fair_probs.get(outcome)
        if not fair_prob or not price:
            continue
        if (price * fair_prob - 1) >= config.EV_THRESHOLD:
            opportunities.append(_make_opportunity(event, price, outcome, fair_prob, num_retail_books))

    return opportunities
