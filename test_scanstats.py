"""Tests for the Pinnacle flat threshold + scan stats / near-miss digest line.
Run: python test_scanstats.py"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["SCAN_STATS_FILE"] = tempfile.mktemp(suffix=".json")

from src import config, ev_calculator as ev, scan_stats, daily_digest

NOW = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)


def book(key, outcomes):
    return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": outcomes}]}


def h2h(fav, dog):
    return [{"name": "Fav", "price": fav}, {"name": "Dog", "price": dog}]


def event(books):
    return {"id": "e1", "sport_key": "tennis_x", "commence_time": "2026-10-19T03:00:00Z",
            "home_team": "Fav", "away_team": "Dog", "bookmakers": books}


SOFT = [book(k, h2h(1.22, 4.5)) for k in ("tab", "ladbrokes_au", "neds", "unibet")]


def test_thresholds_by_anchor():
    assert abs(config.get_edge_threshold(5.0, "pinnacle") - 0.03) < 1e-12          # flat
    assert abs(config.get_edge_threshold(5.0, "retail_consensus") - 0.09) < 1e-12  # old scaling
    old = config.SHARP_EV_SLOPE
    config.SHARP_EV_SLOPE = 0.005
    try:
        assert abs(config.get_edge_threshold(5.0, "pinnacle") - 0.04) < 1e-12
        assert abs(config.get_edge_threshold(2.0, "pinnacle") - 0.03) < 1e-12      # no discount below 3
    finally:
        config.SHARP_EV_SLOPE = old


def test_pinnacle_bet_now_alerts_where_old_scaling_would_not():
    # Pinnacle fair for the dog ~5.74 (shin). Sportsbet (no commission) at 6.0 = ~4.5% edge:
    # clears the flat 3%, would NOT have cleared the old 11% needed at odds of 6.
    books = SOFT + [book("pinnacle", h2h(1.19, 5.3)), book("sportsbet", h2h(1.15, 6.0))]
    out = [o for o in ev.find_positive_ev(event(books)) if o["outcome"] == "Dog"]
    assert len(out) == 1 and out[0]["anchor"] == "pinnacle" and 3 <= out[0]["ev_pct"] < 11, out
    assert config.get_ev_threshold(6.0) > out[0]["ev_pct"] / 100


def test_edge_below_flat_threshold_still_no_alert():
    books = SOFT + [book("pinnacle", h2h(1.19, 5.3)), book("sportsbet", h2h(1.15, 5.8))]   # ~1% edge
    assert [o for o in ev.find_positive_ev(event(books)) if o["outcome"] == "Dog"] == []


def test_consensus_fallback_keeps_scaling_threshold():
    books = SOFT + [book("sportsbet", h2h(1.15, 5.0))]       # no Pinnacle
    out = [o for o in ev.find_positive_ev(event(books)) if o["outcome"] == "Dog"]
    assert out == [] or out[0]["ev_pct"] / 100 >= config.get_ev_threshold(5.0)


def test_stats_counts_and_closest_call():
    stats = scan_stats.new_stats()
    books = SOFT + [book("pinnacle", h2h(1.19, 5.3)), book("sportsbet", h2h(1.15, 5.8))]
    ev.find_positive_ev(event(books), stats)
    assert stats["markets"] == 1 and stats["markets_sharp"] == 1 and stats["outcomes"] == 2
    b = stats["best"]
    assert b["outcome"] in ("Dog", "Fav") and b["gap"] < 0 and b["threshold_pct"] == 3.0
    assert b["matchup"] == "Dog @ Fav" and b["book"] == "sportsbet"
    # a capped (too-good) price is counted but never reported as the closest call
    stats2 = scan_stats.new_stats()
    ev.find_positive_ev(event(SOFT + [book("pinnacle", h2h(1.19, 5.3)), book("sportsbet", h2h(1.15, 9.0))]), stats2)
    assert stats2["capped"] >= 1 and stats2["best"]["price"] != 9.0


def test_record_prune_and_summarize():
    p = config.SCAN_STATS_FILE
    if os.path.exists(p):
        os.remove(p)
    mk = lambda gap, markets=10, sharp=8: {"markets": markets, "markets_sharp": sharp, "outcomes": 20, "capped": 1,
                                           "best": {"gap": gap, "ev_pct": 3 + gap, "threshold_pct": 3.0, "price": 2.1,
                                                    "outcome": "X", "book": "Betfair", "matchup": "A @ B",
                                                    "sport_key": "s", "anchor": "pinnacle"}}
    scan_stats.record_run(mk(-2.5), NOW - timedelta(hours=60))     # too old, pruned on next write
    scan_stats.record_run(mk(-1.0), NOW - timedelta(hours=30))     # kept 48h, outside the 24h summary
    scan_stats.record_run(mk(-0.4), NOW - timedelta(hours=5))
    scan_stats.record_run(mk(-1.8), NOW - timedelta(hours=1))
    scan_stats.record_run({"markets": 0}, NOW)                      # empty run not recorded
    runs = json.load(open(p))
    assert len(runs) == 3, len(runs)
    s = scan_stats.summarize(NOW)
    assert s["runs"] == 2 and s["markets"] == 20 and s["markets_sharp"] == 16 and s["capped"] == 2
    assert s["best"]["gap"] == -0.4
    text = "\n".join(scan_stats.format_lines(s))
    assert "2 runs" in text and "20 market checks (80% priced vs Pinnacle)" in text
    assert "Closest call: X @ 2.1 (Betfair) - A @ B" in text and "-0.4%" not in text and "needed" in text
    assert scan_stats.format_lines(None) == []


def test_digest_includes_summary_and_old_format_still_works():
    summary = {"runs": 38, "markets": 400, "markets_sharp": 380, "capped": 0,
               "best": {"gap": -1.2, "ev_pct": 1.8, "threshold_pct": 3.0, "price": 2.6, "outcome": "Fav",
                        "book": "Betfair", "matchup": "Dog @ Fav", "sport_key": "s", "anchor": "pinnacle"}}
    msg = daily_digest.format_digest([], {}, {}, {}, 19000, NOW, scan_summary=summary)
    assert "Scans: 38 runs" in msg and "Closest call: Fav @ 2.6 (Betfair)" in msg and "+1.8% vs 3.0% needed" in msg
    msg2 = daily_digest.format_digest([], {}, {}, {}, 19000, NOW)
    assert "Closest call" not in msg2 and "Live alerts sent: 0" in msg2


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
