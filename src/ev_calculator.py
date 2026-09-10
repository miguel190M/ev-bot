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
