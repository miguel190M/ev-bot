"""Tests for /open and the one-off 'result needed' reminder. Run: python test_open.py"""
from datetime import datetime, timedelta, timezone

from src import daily_digest as dd, telegram_commands as tc

NOW = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)


def _bet(sport, hours_ago, **kw):
    t = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    b = {"status": "open", "sport_key": sport, "commence_time": t, "home_team": "H", "away_team": "A",
         "outcome": "H", "price": 2.0, "stake": 10.0}
    b.update(kw)
    return b


def test_command_parse():
    assert tc.is_open_command("/open") and tc.is_open_command(" /Outstanding ")
    assert not tc.is_open_command("/stats")


def test_open_text_states():
    L = {"a": _bet("boxing_boxing", 8), "b": _bet("boxing_boxing", 1), "c": _bet("boxing_boxing", -5),
         "d": _bet("boxing_boxing", 9, status="won")}
    t = dd.open_bets_text(L, NOW)
    assert "Open bets (3" in t and "$30" in t
    assert "a · H @ 2.0 ($10) · A @ H · ⏳ needs your result" in t
    assert "b ·" in t and "in play" in t and "c ·" in t and "starts " in t
    assert "d ·" not in t and "/settle" in t
    assert dd.open_bets_text({}, NOW) == "No open bets."


def test_reminder_fires_once_per_bet():
    L = {"a": _bet("boxing_boxing", 8), "b": _bet("boxing_boxing", 1), "e": _bet("basketball_nba", 20)}
    sent = []
    assert dd.remind_awaiting_settlement(L, NOW, sent.append) == 1
    assert len(sent) == 1 and "a ·" in sent[0] and "b ·" not in sent[0] and "e ·" not in sent[0]
    assert dd.remind_awaiting_settlement(L, NOW + timedelta(hours=1), sent.append) == 0    # not again
    L["b"]["commence_time"] = (NOW - timedelta(hours=9)).isoformat().replace("+00:00", "Z")
    assert dd.remind_awaiting_settlement(L, NOW + timedelta(hours=2), sent.append) == 1    # new one only
    assert len(sent) == 2 and "b ·" in sent[1] and "a ·" not in sent[1]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
