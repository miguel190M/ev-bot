"""Sanity-check the credit-saving scheduling logic. No network needed.
Run: python test_scheduling.py"""
from datetime import datetime, timedelta, timezone
from src import scheduling

now = datetime(2026, 8, 1, 6, 0, 0, tzinfo=timezone.utc)  # fixed reference point

def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")

# Case 1: nothing scheduled at all -> should NOT trigger a paid call
assert scheduling.starting_soon([], window_hours=3, now=now) is False

# Case 2: game starts in 2 hours, window is 3 hours -> SHOULD trigger
events = [{"commence_time": iso(now + timedelta(hours=2))}]
assert scheduling.starting_soon(events, window_hours=3, now=now) is True

# Case 3: game starts in 5 hours, window is 3 hours -> should NOT trigger yet
events = [{"commence_time": iso(now + timedelta(hours=5))}]
assert scheduling.starting_soon(events, window_hours=3, now=now) is False

# Case 4: game already started 1 hour ago (live) -> should NOT trigger
# (this is what stops an in-play game from costing a credit on every run)
events = [{"commence_time": iso(now - timedelta(hours=1))}]
assert scheduling.starting_soon(events, window_hours=3, now=now) is False

# Case 5: mixed list - one far off, one imminent -> SHOULD trigger
events = [
    {"commence_time": iso(now + timedelta(hours=20))},
    {"commence_time": iso(now + timedelta(minutes=30))},
]
assert scheduling.starting_soon(events, window_hours=3, now=now) is True

# Case 6: starts in exactly the window boundary -> SHOULD trigger (inclusive)
events = [{"commence_time": iso(now + timedelta(hours=3))}]
assert scheduling.starting_soon(events, window_hours=3, now=now) is True

print("✅ All scheduling tests passed.")
