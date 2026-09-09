"""
+EV detection, anchored on Betfair Exchange when available.

For each event/market, two possible methods are used depending on data
availability - every opportunity is tagged with which one applied.

PRIMARY METHOD: Betfair Exchange anchor
  Betfair Exchange (`betfair_ex_au`) reports two real, opposing prices for
  each outcome: the best price you can BACK it at, and the best price you
  can LAY it at (bet against it). Because these come from real money on
  both sides of the market rather than one bookmaker's opinion, the
  midpoint between them is a much tighter fair-value estimate than de-vigging
  a single retail book:
      fair_prob = (1/back_price + 1/lay_price) / 2   [normalized to sum to 1]
  Every retail bookmaker's price is then checked against this line. Betfair
  itself is excluded from the "target" side - it's the ruler, not what's
  being measured.

FALLBACK METHOD: retail median consensus
  Used only when Betfair has no odds for that event (thin liquidity on a
  smaller market). Each retail book is de-vigged individually, and to judge
  one book's price we take the MEDIAN de-vigged probability from every
  OTHER book (leave-one-out, so a book can't inflate its own baseline, and
  median rather than mean so one outlier book can't drag everyone else's
  baseline with it). This is weaker signal than the Betfair anchor - AU
  retail books share ownership groups and often shade off each other - so
  treat fallback-tagged alerts as lower confidence.

EV% = (bookmaker's decimal odds x fair probability) - 1
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


def betfair_fair_probabilities(event: dict):
    """Derive fair probabilities from Betfair Exchange's back/lay spread.
    Returns None if Betfair isn't quoting both sides for this event."""
    betfair = next((bm for bm in event.get("bookmakers", []) if bm["key"] == config.BETFAIR_KEY), None)
    if not betfair:
        return None
    markets = {m["key"]: m for m in betfair.get("markets", [])}
    back_market, lay_market = markets.get("h2h"), markets.get("h2h_lay")
    if not back_market or not lay_market:
        return None

    back = {o["name"]: o["price"] for o in back_market.get("outcomes", [])}
    lay = {o["name"]: o["price"] for o in lay_market.get("outcomes", [])}

    fair = {}
    for name, back_price in back.items():
        lay_price = lay.get(name)
        if not back_price or not lay_price:
            continue
        fair[name] = (1 / back_price + 1 / lay_price) / 2

    total = sum(fair.values())
    if total <= 0:
        return None
    return {name: p / total for name, p in fair.items()}


def _make_opportunity(event, book_key, book_title, outcome, price, fair_prob, anchor, num_books):
    return {
        "event_id": event["id"],
        "sport_key": event["sport_key"],
        "commence_time": event["commence_time"],
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
        "bookmaker_key": book_key,
        "bookmaker_title": book_title,
        "outcome": outcome,
        "price": price,
        "fair_probability": round(fair_prob, 4),
        "fair_odds": round(1 / fair_prob, 3),
        "ev_pct": round((price * fair_prob - 1) * 100, 2),
        "anchor": anchor,
        "num_books": num_books,
    }


def find_positive_ev(event: dict) -> list[dict]:
    """Scan a single event's bookmakers for +EV prices. Returns a list of
    opportunity dicts, one per (bookmaker, outcome) that clears the threshold."""
    opportunities = []
    book_prices, book_titles = _extract_book_prices(event)
    if len(book_prices) < 2:
        return opportunities

    fair_probs = betfair_fair_probabilities(event)

    if fair_probs is not None:
        # --- Primary: Betfair Exchange anchor ---
        for book_key, prices in book_prices.items():
            if book_key == config.BETFAIR_KEY:
                continue  # don't evaluate the anchor against itself
            for outcome, price in prices.items():
                fair_prob = fair_probs.get(outcome)
                if not fair_prob or not price:
                    continue
                if (price * fair_prob - 1) >= config.EV_THRESHOLD:
                    opportunities.append(_make_opportunity(
                        event, book_key, book_titles[book_key], outcome, price,
                        fair_prob, anchor="betfair_exchange", num_books=len(book_prices),
                    ))
        return opportunities

    # --- Fallback: retail median consensus (Betfair had no odds here) ---
    book_devig = {k: devig_probabilities([{"name": n, "price": p} for n, p in v.items()])
                  for k, v in book_prices.items()}
    book_keys = list(book_devig.keys())
    if len(book_keys) < config.MIN_BOOKS:
        return opportunities  # not enough books to trust a consensus

    outcome_names = set()
    for probs in book_devig.values():
        outcome_names.update(probs.keys())

    for target_book in book_keys:
        other_books = [b for b in book_keys if b != target_book]
        for outcome in outcome_names:
            other_probs = [book_devig[b][outcome] for b in other_books if outcome in book_devig[b]]
            if len(other_probs) < config.MIN_BOOKS - 1:
                continue
            fair_prob = statistics.median(other_probs)
            price = book_prices[target_book].get(outcome)
            if not price or fair_prob <= 0:
                continue
            if (price * fair_prob - 1) >= config.EV_THRESHOLD:
                opportunities.append(_make_opportunity(
                    event, target_book, book_titles[target_book], outcome, price,
                    fair_prob, anchor="retail_consensus", num_books=len(book_keys),
                ))
    return opportunities
