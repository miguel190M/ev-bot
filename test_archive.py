"""Pre-Pinnacle bets are archived out of the live ledger. Run: python test_archive.py"""
import json
import os
import tempfile

from src import bets, config


def bet(ct, status="lost"):
    return {"commence_time": ct, "status": status, "stake": 10.0, "price": 2.0, "profit": -10.0, "outcome": "X"}


def test_archive_moves_old_bets_once_and_merges():
    path = tempfile.mktemp(suffix=".json")
    L = {"old1": bet("2026-09-21T10:30:00Z"), "old2": bet("2026-10-12T03:00:00Z", "won"),
         "new1": bet("2026-10-12T04:20:00Z"), "new2": bet("2026-11-05T00:00:00Z", "open")}
    assert bets.archive_before(L, config.PINNACLE_ERA_START, path) == ["old1", "old2"]
    assert sorted(L) == ["new1", "new2"]
    assert sorted(json.load(open(path))) == ["old1", "old2"]
    assert bets.archive_before(L, config.PINNACLE_ERA_START, path) == []          # idempotent
    # a later archive pass merges into the existing file rather than overwriting it
    L["old3"] = bet("2026-10-01T00:00:00Z")
    assert bets.archive_before(L, config.PINNACLE_ERA_START, path) == ["old3"]
    assert sorted(json.load(open(path))) == ["old1", "old2", "old3"]


def test_cutoff_is_the_pinnacle_go_live_time_and_stats_use_only_the_rest():
    assert config.PINNACLE_ERA_START == "2026-10-12T03:34:36Z"
    L = {"a": bet("2026-09-21T10:30:00Z"), "b": bet("2026-11-05T00:00:00Z", "won")}
    L["b"]["profit"] = 10.0
    bets.archive_before(L, config.PINNACLE_ERA_START, tempfile.mktemp())
    assert list(L) == ["b"]
    s = bets.compute_stats(L)
    assert (s["wins"], s["losses"]) == (1, 0) and s["total_profit"] == 10.0, s


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
