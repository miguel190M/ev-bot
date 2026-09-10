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
