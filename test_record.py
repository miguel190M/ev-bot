"""Tests for /record (win-loss, $ profit, ROI, CLV and open bets per sport).
Run: python test_record.py"""
from unittest import mock

from src import breakdown, telegram_commands as tc
import main


def b(sport, status, stake=10.0, price=2.0, profit=None, clv=None):
    if profit is None:
        profit = {"won": stake * (price - 1), "lost": -stake}.get(status, 0.0 if status == "void" else None)
    return {"sport_key": sport, "status": status, "stake": stake, "price": price, "profit": profit,
            "net_clv_pct": clv}


LEDGER = {
    "a": b("boxing_boxing", "won", 20, 1.5, clv=-4.0), "b": b("boxing_boxing", "won", 10, 2.0, clv=-2.0),
    "c": b("boxing_boxing", "lost", 10), "d": b("boxing_boxing", "open"),
    "e": b("tennis_wta_wuhan_open", "lost", 10), "f": b("tennis_atp_china_open", "lost", 10),
    "g": b("tennis_wta_x", "void"), "h": b("cricket_big_bash", "open"),
}


def test_command_parse():
    assert tc.is_record_command("/record") and tc.is_record_command(" /Sports ")
    assert not tc.is_record_command("/stats") and not tc.is_record_command("/breakdown")


def test_record_numbers():
    out = breakdown.record(LEDGER)
    box = next(l for l in out.splitlines() if l.startswith("Boxing:"))
    assert "2W-1L" in box and "+$10.00 on $40" in box and "ROI +25%" in box
    assert "CLV -3.0%" in box and "1 open" in box
    wta = next(l for l in out.splitlines() if l.startswith("Tennis WTA:"))
    assert "0W-1L-1V" in wta and "-$10.00" in wta
    assert any(l.startswith("Tennis ATP:") and "0W-1L" in l for l in out.splitlines())
    big = next(l for l in out.splitlines() if "Big Bash" in l)
    assert "0W-0L" in big and "1 open" in big and "ROI n/a" in big            # open-only sport still listed
    total = next(l for l in out.splitlines() if l.startswith("TOTAL:"))
    assert "2W-3L-1V" in total and "-$10.00 on $60" in total and "2 open" in total


def test_sorted_by_settled_count_and_empty():
    lines = breakdown.record(LEDGER).splitlines()
    names = [l.split(":")[0] for l in lines[1:] if ":" in l and not l.startswith("TOTAL")]
    assert names[0] == "Boxing"
    assert breakdown.record({}) == "No bets logged yet."


def test_command_replies_with_record():
    sent = []
    with mock.patch.object(tc, "get_new_messages", return_value=["/record"]), \
         mock.patch.object(tc, "send_message", side_effect=sent.append):
        main.process_commands({}, dict(LEDGER))
    assert len(sent) == 1 and sent[0].startswith("📒 Record by sport") and "TOTAL:" in sent[0]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
