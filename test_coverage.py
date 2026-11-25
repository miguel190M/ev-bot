"""Bookmaker coverage log + /books. Run: python test_coverage.py"""
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest import mock

from src import config, coverage, telegram_commands as tc
import main

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def bm(key, title, *markets):
    return {"key": key, "title": title, "markets": [
        {"key": m, "outcomes": [{"name": "A", "price": 1.9}, {"name": "B", "price": 1.9}]} for m in markets]}


def ev(*books):
    return {"id": "e", "bookmakers": list(books)}


def _fresh():
    d = tempfile.mkdtemp()
    return mock.patch.object(config, "COVERAGE_FILE", os.path.join(d, "cov.json"))


def test_update_counts_books_markets_and_slate():
    cov = coverage.update({}, {"basketball_nba": [
        ev(bm("pinnacle", "Pinnacle", "h2h", "totals", "spreads"), bm("sportsbet", "SportsBet", "h2h", "totals"),
           bm("playup", "PlayUp", "h2h")),
        ev(bm("pinnacle", "Pinnacle", "h2h", "totals"), bm("sportsbet", "SportsBet", "h2h"))]}, NOW)
    assert cov["runs"] == 1 and cov["slate"]["basketball_nba"] == {"h2h": 2, "totals": 2, "spreads": 1}
    assert cov["books"]["sportsbet"]["sports"]["basketball_nba"] == {"h2h": 2, "totals": 1}
    assert cov["books"]["playup"]["sports"]["basketball_nba"] == {"h2h": 1}
    cov = coverage.update(cov, {"basketball_nba": [ev(bm("playup", "PlayUp", "h2h", "totals"))]}, NOW)
    assert cov["runs"] == 2 and cov["books"]["playup"]["sports"]["basketball_nba"] == {"h2h": 2, "totals": 1}
    # a market with fewer than two outcomes is not a quote
    one = {"key": "tab", "title": "TAB", "markets": [{"key": "h2h", "outcomes": [{"name": "A", "price": 2}]}]}
    assert "tab" not in coverage.update({}, {"x": [ev(one)]}, NOW)["books"] or \
        coverage.update({}, {"x": [ev(one)]}, NOW)["books"]["tab"]["sports"] == {}


def test_report_shows_nextbet_coverage_and_never_seen():
    with _fresh():
        assert "No coverage data yet" in coverage.report()
        coverage.record_run({"basketball_nba": [ev(bm("playup", "PlayUp", "h2h"), bm("sportsbet", "SportsBet", "h2h", "totals"),
                                                  bm("pinnacle", "Pinnacle", "h2h", "totals"))],
                             "americanfootball_nfl": [ev(bm("sportsbet", "SportsBet", "h2h"))]})
        r = coverage.report()
        assert "NextBet (feed key: playup): h2h 1/1 (100%)" in r and "totals" not in r.split("NextBet")[1].split("\n")[0]
        assert "SportsBet: h2h 2/2 (100%) · totals 1/1 (100%)" in r
        assert "betfair_ex_au: never seen in the feed" in r                # bettable but absent
        assert "Pinnacle" not in r                                          # only bettable books in the summary
        assert "Pinnacle: h2h 1/2" not in coverage.report("pinnacle") and "Pinnacle" in coverage.report("pinnacle")
        assert "NextBet (feed key: playup)" in coverage.report("nextbet")   # name lookups work
        assert "No book matching 'bet365'" in coverage.report("bet365")


def test_command_parsing_and_reply():
    assert tc.parse_books_command("/books") == "" and tc.parse_books_command("/coverage") == ""
    assert tc.parse_books_command("/books Pinnacle") == "Pinnacle"
    assert tc.parse_books_command("/bet ab12 10") is None and tc.parse_books_command("hello") is None
    sent = []
    with _fresh(), mock.patch.object(tc, "get_new_messages", return_value=["/books"]), \
            mock.patch.object(tc, "send_message", side_effect=sent.append):
        coverage.record_run({"basketball_nba": [ev(bm("playup", "PlayUp", "h2h"))]})
        main.process_commands({}, {})
    assert sent and "NextBet (feed key: playup)" in sent[0]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
