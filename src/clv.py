"""Closing-line capture for CLV.

Previously a closing snapshot was only taken when the regular scan happened
to re-check an open bet's event before kickoff. Bets logged late, or on
events whose last pre-kickoff run was skipped or fell in the sleep window,
ended up with no CLV at all. This fills that gap:

  1. Free: any open, not-yet-started bet whose sport's odds were already
     pulled this run gets its fair price refreshed from that data - the
     latest pre-kickoff value always wins.
  2. Paid, only when needed: an open bet starting within
     CLV_CAPTURE_MINUTES whose sport wasn't fetched this run triggers one
     odds pull for that sport (shared by every open bet in it).

A bet logged via /bet after kickoff can never get a closing snapshot -
log bets before the game starts.
"""
from datetime import datetime, timezone

from . import config, odds_fetcher, ev_calculator


def _start(bet):
    return datetime.fromisoformat(bet["commence_time"].replace("Z", "+00:00"))


def capture_closing(bet_ledger: dict, odds_cache: dict, now: datetime | None = None) -> int:
    """Returns credits used. Mutates bets (closing_fair_odds,
    closing_captured_at) and odds_cache in place."""
    now = now or datetime.now(timezone.utc)
    pending = [b for b in bet_ledger.values() if b["status"] == "open" and _start(b) > now]
    if not pending:
        return 0

    credits = 0
    for sport_key in {b["sport_key"] for b in pending}:
        if sport_key in odds_cache["events"]:
            continue
        due = any((_start(b) - now).total_seconds() / 60 <= config.CLV_CAPTURE_MINUTES
                  for b in pending if b["sport_key"] == sport_key)
        if not due:
            continue
        try:
            events, remaining, used = odds_fetcher.get_odds(sport_key)
        except Exception as e:
            print(f"  CLV capture: {sport_key} odds fetch failed ({e})")
            continue
        odds_cache["events"][sport_key] = events
        odds_cache["remaining"] = remaining
        credits += int(used or 0)
        print(f"  CLV capture: pulled {sport_key} for pre-kickoff snapshot ({used} credits)")

    captured = 0
    for b in pending:
        events = odds_cache["events"].get(b["sport_key"]) or []
        event = next((e for e in events if e["id"] == b["event_id"]), None)
        if not event:
            continue
        fair = ev_calculator.get_reference_fair_odds(event, b["outcome"], b.get("market_key", "h2h"))
        if fair:
            b["closing_fair_odds"] = fair
            b["closing_captured_at"] = now.isoformat()
            captured += 1
    if captured:
        print(f"  CLV capture: refreshed closing snapshot on {captured} open bet(s)")
    odds_cache["credits_used"] = odds_cache.get("credits_used", 0) + credits
    return credits
