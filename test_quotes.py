"""/quotes: latest per-book h2h prices. Run: python test_quotes.py"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import config, quotes, telegram_commands as tc
import main

NOW = datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)


def ts(h): return (NOW + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def bm(key, a, b, home="New York Knicks", away="Miami Heat"):
    return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": [
        {"name": away, "price": b}, {"name": home, "price": a}]}]}


def ev(h, home, away, *books):
    return {"id": home, "home_team": home, "away_team": away, "commence_time": ts(h), "bookmakers": list(books)}


def _fresh():
    return mock.patch.object(config, "QUOTES_FILE", os.path.join(tempfile.mkdtemp(), "q.json"))


def test_update_keeps_relevant_books_and_drops_started_games():
    store = quotes.update({}, {"basketball_nba": [
        ev(1, "New York Knicks", "Miami Heat", bm("playup", 1.63, 2.30), bm("pinnacle", 1.60, 2.40), bm("tab", 1.7, 2.2)),
        ev(-1, "A", "B", bm("playup", 1.5, 2.5, "A", "B"))]}, NOW)          # already started
    rows = store["basketball_nba"]["events"]
    assert len(rows) == 1 and set(rows[0]["books"]) == {"playup", "pinnacle"}   # tab not kept
    # a sport not pulled this run keeps its previous entry; a re-pulled sport is replaced
    store = quotes.update(store, {"icehockey_nhl": [ev(2, "X", "Y", bm("sportsbet", 1.9, 1.9, "X", "Y"))]}, NOW)
    assert set(store) == {"basketball_nba", "icehockey_nhl"}
    store = quotes.update(store, {"basketball_nba": [ev(1, "New York Knicks", "Miami Heat", bm("playup", 1.65, 2.28))]}, NOW)
    assert store["basketball_nba"]["events"][0]["books"]["playup"]["New York Knicks"] == 1.65
    # once the game has started it disappears
    assert "basketball_nba" not in quotes.update(store, {}, NOW + timedelta(hours=2))


def test_empty_report():
    with _fresh():
        assert "No stored prices" in quotes.report()


def test_report_with_fixed_clock():
    with _fresh():
        store = quotes.update({}, {"basketball_nba": [
            ev(1, "New York Knicks", "Miami Heat", bm("playup", 1.63, 2.30), bm("sportsbet", 1.62, 2.35), bm("pinnacle", 1.60, 2.40)),
            ev(2, "Boston Celtics", "Atlanta Hawks", bm("playup", 1.26, 3.80, "Boston Celtics", "Atlanta Hawks"))]}, NOW)
        import json
        from pathlib import Path
        Path(config.QUOTES_FILE).write_text(json.dumps(store))
        r = quotes.report(now=NOW + timedelta(minutes=5))
        assert "New York Knicks v Miami Heat" in r and "scanned 5m ago" in r
        assert "NextBet   1.63/2.30" in r and "SportsBet 1.62/2.35" in r and "Pinnacle  1.60/2.40" in r
        assert "NextBet   1.26/3.80" in r
        only = quotes.report("knicks", now=NOW)
        assert "Knicks" in only and "Celtics" not in only
        assert "Celtics" in quotes.report("nba", now=NOW) and "No stored prices matching 'lakers'" in quotes.report("lakers", now=NOW)


def test_command_parsing_and_reply():
    assert tc.parse_quotes_command("/quotes") == "" and tc.parse_quotes_command("/quotes Knicks") == "Knicks"
    assert tc.parse_quotes_command("/price ab12 2.0") is None and tc.parse_quotes_command("/books") is None
    sent = []
    with _fresh(), mock.patch.object(tc, "get_new_messages", return_value=["/quotes"]), \
            mock.patch.object(tc, "send_message", side_effect=sent.append):
        main.process_commands({}, {})
    assert sent and "No stored prices" in sent[0]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
