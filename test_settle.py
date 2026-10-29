"""Tests for manual settling (/settle) and the digest's awaiting-settlement list.
Run: python test_settle.py"""
from datetime import datetime, timedelta, timezone

from src import bets, config, daily_digest, telegram_commands as tc

NOW = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)


def _bet(sport, hours_ago, price=2.0, stake=10.0, commission=0.0):
    t = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"status": "open", "sport_key": sport, "event_id": "e", "commence_time": t,
            "home_team": "H", "away_team": "A", "outcome": "H", "price": price,
            "stake": stake, "commission": commission, "market_key": "h2h", "profit": None}


def test_parse():
    assert tc.parse_settle_command("/settle 5b88 won") == ("5b88", "won")
    assert tc.parse_settle_command("/settle 5442e-1 LOST") == ("5442e-1", "lost")
    assert tc.parse_settle_command("/won 976b") == ("976b", "won")
    assert tc.parse_settle_command("/void 1cf4") == ("1cf4", "void")
    assert tc.parse_settle_command("/settle 5b88 maybe") is None
    assert tc.parse_settle_command("/bet 5b88 10") is None
    assert tc.parse_settle_command("/stats") is None


def test_settle_math_with_commission():
    b = _bet("boxing_boxing", 10, price=1.14, stake=20, commission=0.06)
    bets.settle_manually(b, "won")
    assert b["status"] == "won" and b["profit"] == round(20 * 0.14 * 0.94, 2)
    b = _bet("boxing_boxing", 10, price=2.45, stake=10)
    bets.settle_manually(b, "lost")
    assert b["status"] == "lost" and b["profit"] == -10.0
    b = _bet("boxing_boxing", 10)
    bets.settle_manually(b, "void")
    assert b["status"] == "void" and b["profit"] == 0.0 and b["settled_manually"]


def test_awaiting_list_rules():
    ledger = {
        "a": _bet("boxing_boxing", 8),                 # over 6h: listed
        "b": _bet("boxing_boxing", 2),                 # still on: not listed
        "c": _bet("cricket_test_match", 30),           # test, under 72h: not listed
        "d": _bet("cricket_test_match", 80),           # test, over 72h: listed
        "e": _bet("basketball_nba", 20),               # auto-settled sport: never listed
        "f": {**_bet("mma_mixed_martial_arts", 12), "status": "won"},   # already settled
    }
    got = [bid for bid, _ in daily_digest.awaiting_settlement(ledger, NOW)]
    assert got == ["d", "a"], got      # oldest first


def test_digest_shows_section_and_settled_leaves_it():
    ledger = {"a": _bet("boxing_boxing", 8)}
    txt = daily_digest.format_digest([], {}, {}, ledger, "18000", NOW)
    assert "Awaiting your result" in txt and "a ·" in txt
    bets.settle_manually(ledger["a"], "won")
    ledger["a"]["resolved_at"] = NOW.isoformat()
    txt = daily_digest.format_digest([], {}, {}, ledger, "18000", NOW)
    assert "Awaiting your result" not in txt and "Settled: 1W-0L" in txt


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
