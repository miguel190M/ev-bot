"""Tests for persisting picks suppressed by MAX_EV_PCT and the /suppressed report.
Run: python test_suppressed.py"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ["SUPPRESSED_FILE"] = tempfile.mktemp(suffix=".json")
os.environ["SCAN_STATS_FILE"] = tempfile.mktemp(suffix=".json")

from src import config, ev_calculator as ev, scan_stats, telegram_commands as tc
import main

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)


def book(key, outcomes):
    return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": outcomes}]}


def h2h(fav, dog):
    return [{"name": "Fav", "price": fav}, {"name": "Dog", "price": dog}]


def event(books):
    return {"id": "e1", "sport_key": "tennis_x", "commence_time": "2026-11-07T08:00:00Z",
            "home_team": "Fav", "away_team": "Dog", "bookmakers": books}


def reset():
    p = config.SUPPRESSED_FILE
    if os.path.exists(p):
        os.remove(p)


def pick(price=9.0, ev_pct=55.0, book_="sportsbet", sport="tennis_x"):
    return {"sport_key": sport, "matchup": "Dog @ Fav", "market": "h2h", "outcome": "Dog", "book": book_,
            "price": price, "ev_pct": ev_pct, "anchor": "pinnacle", "fair_odds": 5.8, "sharp_odds": 5.3,
            "consensus_odds": 4.5, "commence_time": "2026-11-07T08:00:00Z"}


def test_calculator_collects_capped_picks():
    soft = [book(k, h2h(1.22, 4.5)) for k in ("tab", "ladbrokes_au", "neds", "unibet")]
    stats = scan_stats.new_stats()
    ev.find_positive_ev(event(soft + [book("pinnacle", h2h(1.19, 5.3)), book("sportsbet", h2h(1.15, 9.0))]), stats)
    assert stats["capped"] >= 1 and len(stats["capped_picks"]) == stats["capped"]
    c = stats["capped_picks"][0]
    assert c["price"] == 9.0 and c["book"] == "sportsbet" and c["ev_pct"] > config.MAX_EV_PCT
    assert c["sharp_odds"] and c["fair_odds"] and c["anchor"] == "pinnacle"
    json.dumps(stats["capped_picks"])  # serialisable


def test_record_merge_and_prune():
    reset()
    scan_stats.record_suppressed([pick()], NOW)
    scan_stats.record_suppressed([pick(price=10.0, ev_pct=70.0), pick(book_="tab", price=8.0, ev_pct=40.0)],
                                 NOW + timedelta(minutes=30))
    store = json.load(open(config.SUPPRESSED_FILE))
    assert len(store) == 2
    sb = next(v for v in store.values() if v["book"] == "sportsbet")
    assert sb["seen"] == 2 and sb["max_ev_pct"] == 70.0 and sb["price"] == 10.0
    assert sb["first_seen"] == NOW.isoformat()
    # entries not seen for 48h are dropped
    scan_stats.record_suppressed([], NOW + timedelta(hours=49))
    assert json.load(open(config.SUPPRESSED_FILE)) == {}


def test_report_empty_and_populated():
    reset()
    assert "No picks were suppressed" in scan_stats.suppressed_report(NOW)
    scan_stats.record_suppressed([pick(), pick(book_="tab", price=8.0, ev_pct=40.0)], NOW)
    out = scan_stats.suppressed_report(NOW + timedelta(hours=1))
    assert "2 unique picks" in out and "vs Pinnacle 2" in out
    assert out.index("+55%") < out.index("+40%")                 # biggest edge first
    assert "Dog @ 9.0 (sportsbet)" in out and "Pinnacle 5.3" in out and "fair 5.8" in out
    # outside the window it is not shown
    assert "No picks were suppressed" in scan_stats.suppressed_report(NOW + timedelta(hours=30))


def test_summary_line_points_to_command():
    lines = scan_stats.format_lines({"runs": 3, "markets": 10, "markets_sharp": 8, "capped": 5, "best": None})
    assert any("5" in l and "/suppressed" in l for l in lines)


def test_command_parse_and_reply():
    assert tc.is_suppressed_command("/suppressed") and tc.is_suppressed_command(" /TooGood ")
    assert not tc.is_suppressed_command("/record")
    reset()
    scan_stats.record_suppressed([pick()], datetime.now(timezone.utc))
    sent = []
    with mock.patch.object(tc, "get_new_messages", return_value=["/suppressed"]), \
         mock.patch.object(tc, "send_message", side_effect=sent.append):
        main.process_commands({}, {})
    assert len(sent) == 1 and sent[0].startswith("🚫 Suppressed") and "Dog @ 9.0" in sent[0]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
