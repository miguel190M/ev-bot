"""Decide whether it's worth spending an odds-API credit on a sport right
now, based on whether anything is starting soon. Keeps the free /events
endpoint doing the frequent checking, and only the paid /odds endpoint gets
called when it's actually likely to matter."""

from datetime import datetime, timezone


def starting_soon(events: list[dict], window_hours: float, now: datetime | None = None) -> bool:
    """True if any event starts between now and now + window_hours. Events
    that have already started are excluded (that's what keeps a live game
    from triggering a paid call on every single run while it's in progress)."""
    now = now or datetime.now(timezone.utc)
    for ev in events:
        commence = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        delta_hours = (commence - now).total_seconds() / 3600
        if 0 <= delta_hours <= window_hours:
            return True
    return False
