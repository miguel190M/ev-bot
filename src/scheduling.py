"""Decide whether it's worth spending an odds-API credit on a sport right
now, based on whether anything is starting soon. Keeps the free /events
endpoint doing the frequent checking, and only the paid /odds endpoint gets
called when it's actually likely to matter.

Also filters WHICH events get evaluated once odds are fetched - a fetched
batch can include events far outside the window even when the sport as a
whole was worth calling (e.g. a tennis tournament spanning two weeks, where
one imminent match justified the credit but a final scheduled 11 days out
rode along in the same response)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def _events_within_window(events: list[dict], window_hours: float, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    result = []
    for ev in events:
        commence = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        delta_hours = (commence - now).total_seconds() / 3600
        if 0 <= delta_hours <= window_hours:
            result.append(ev)
    return result


def starting_soon(events: list[dict], window_hours: float, now: datetime | None = None) -> bool:
    """True if any event starts between now and now + window_hours. Events
    that have already started are excluded (that's what keeps a live game
    from triggering a paid call on every single run while it's in progress).
    Use this on the free /events response to decide whether a sport is
    worth spending a credit on at all."""
    return len(_events_within_window(events, window_hours, now)) > 0


def filter_starting_soon(events: list[dict], window_hours: float, now: datetime | None = None) -> list[dict]:
    """Return only the events starting within window_hours from now. Use
    this on the paid /odds response to decide which events actually get
    evaluated for +EV - fetching odds for a sport doesn't mean every event
    in the response is near-term."""
    return _events_within_window(events, window_hours, now)


def is_sleep_window(start_hour: int, end_hour: int, now: datetime | None = None) -> bool:
    """True if the current Sydney local time falls within [start_hour,
    end_hour). Uses the Australia/Sydney IANA timezone, which already
    encodes exactly when AEST <-> AEDT happens each year - so '1am' always
    means 1am Sydney time, whichever UTC offset that currently is, with no
    manual adjustment needed across the daylight-saving switch."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(SYDNEY)
    return start_hour <= local.hour < end_hour


def is_monthly_digest_due(last_sent_month: str, now: datetime | None = None) -> tuple[bool, str]:
    """True (with the current 'YYYY-MM' label) if today is the 1st of the
    month in Sydney local time and a digest hasn't already gone out this
    month. Checking the month label rather than the exact date/time means
    any run during the 1st can send it - so the sleep window blocking the
    1am-7am runs on the 1st doesn't matter, since the day still has ~17
    more hourly opportunities to catch it afterward."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(SYDNEY)
    current_month = local.strftime("%Y-%m")
    due = local.day == 1 and current_month != last_sent_month
    return due, current_month
