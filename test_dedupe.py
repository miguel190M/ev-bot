"""Tests: a pick you've already logged must not alert/list again, and /bet can't
double-log by accident. Run: python test_dedupe.py"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import bets, config, daily_digest, telegram_commands as tc
import main

NOW = datetime.now(timezone.utc)
T = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")


def opp(book="Betfair", outcome="H", eid="e1", market="h2h", ev=5.0):
    return {"event_id": eid, "sport_key": "boxing_boxing", "commence_time": T, "home_team": "H", "away_team": "A",
            "market_key": market, "bookmaker_key": book.lower(), "bookmaker_title": book, "outcome": outcome,
            "price": 2.0, "ev_pct": ev, "anchor": "pinnacle", "fair_odds": 1.9, "commission": 0.0}


def ledger_with(o, status="open"):
    b = {"event_id": o["event_id"], "market_key": o["market_key"], "outcome": o["outcome"],
         "bookmaker_title": o["bookmaker_title"], "status": status, "stake": 10.0, "price": 2.0}
    return {"abcd": b}


def test_find_logged_scopes():
    L = ledger_with(opp())
    assert bets.find_logged(opp(), L) == "abcd"
    assert bets.find_logged(opp("SportsBet"), L, "outcome") == "abcd"          # same pick, other book
    assert bets.find_logged(opp("SportsBet"), L, "book") is None
    assert bets.find_logged(opp(outcome="A"), L) is None                       # other side
    assert bets.find_logged(opp(eid="e2"), L) is None
    assert bets.find_logged(opp(market="totals"), L) is None


def test_drop_logged_respects_setting():
    L = ledger_with(opp())
    ops = [opp(), opp("SportsBet"), opp(outcome="A")]
    with mock.patch.object(config, "DEDUPE_LOGGED_BETS", "outcome"):
        assert [o["outcome"] + o["bookmaker_title"] for o in bets.drop_logged(ops, L)] == ["A" + "Betfair"]
    with mock.patch.object(config, "DEDUPE_LOGGED_BETS", "book"):
        assert len(bets.drop_logged(ops, L)) == 2
    with mock.patch.object(config, "DEDUPE_LOGGED_BETS", "off"):
        assert len(bets.drop_logged(ops, L)) == 3


def test_bet_command_double_log_guard():
    o = opp()
    cands = {"c1": o, "c2": opp()}                       # two alert ids for the same pick
    L = {}
    sent = []
    def run(msgs):
        with mock.patch.object(tc, "get_new_messages", return_value=msgs), \
             mock.patch.object(tc, "send_message", side_effect=sent.append):
            main.process_commands(cands, L)
    run(["/bet c1 10"]);              assert len(L) == 1
    run(["/bet c2 10"]);              assert len(L) == 1 and "Already logged" in sent[-1] and "again" in sent[-1]
    run(["/bet c2 10 again"]);        assert len(L) == 2
    assert tc.parse_bet_command("/bet c2 10 again") == ("c2", 10.0) and tc.is_bet_again("/bet c2 10 again")
    assert not tc.is_bet_again("/bet c2 10")


def _scan(ledger):
    alerts = []
    ev = [{"id": "e1", "commence_time": T, "home_team": "H", "away_team": "A", "bookmakers": []}]
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            with mock.patch.object(main.odds_fetcher, "get_sports_to_scan", return_value=["boxing_boxing"]), \
                 mock.patch.object(main.odds_fetcher, "get_events", return_value=ev), \
                 mock.patch.object(main.odds_fetcher, "get_odds", return_value=(ev, "19000", "2")), \
                 mock.patch.object(main.ev_calculator, "find_positive_ev", return_value=[opp(), opp(outcome="A")]), \
                 mock.patch.object(main.telegram_alerts, "send_alert", side_effect=lambda o, bid: alerts.append(o["outcome"])):
                main.run_scan({}, ledger, {"events": {}, "remaining": None, "credits_used": 0})
        finally:
            os.chdir(old)
    return alerts


def test_scan_does_not_realert_logged_pick():
    assert sorted(_scan({})) == ["A", "H"]
    assert _scan(ledger_with(opp())) == ["A"]            # H already bet on; the other side still alerts


def test_digest_slate_skips_logged_pick():
    ledger = ledger_with(opp())
    with mock.patch.object(daily_digest, "collect_slate", return_value=[opp(), opp(outcome="A")]), \
         mock.patch.object(daily_digest, "_find_or_register",
                           side_effect=lambda o, c: c.setdefault("id" + o["outcome"], {}) and "id" + o["outcome"] or ("id" + o["outcome"])), \
         mock.patch.object(daily_digest.telegram_commands, "send_message") as send, \
         mock.patch.object(daily_digest.bets, "save_digest_state"), \
         mock.patch.object(daily_digest.scan_stats, "summarize", return_value=None):
        daily_digest.send_daily_digest_if_due({}, ledger, {"events": {}, "remaining": "1"},
                                              now=datetime(2026, 10, 29, 22, 5, tzinfo=timezone.utc))
    msg = send.call_args[0][0]
    assert "[idA]" in msg and "[idH]" not in msg


def test_commands_run_before_scan():
    order = []
    with mock.patch.object(main.config, "ODDS_API_KEY", "k"), \
         mock.patch.object(main.scheduling, "is_sleep_window", return_value=False), \
         mock.patch.object(main.bets, "load_candidates", return_value={}), \
         mock.patch.object(main.bets, "load_bets", return_value={}), \
         mock.patch.object(main.bets, "save_candidates"), mock.patch.object(main.bets, "save_bets"), \
         mock.patch.object(main, "process_commands", side_effect=lambda *a: order.append("commands")), \
         mock.patch.object(main, "run_scan", side_effect=lambda *a: order.append("scan") or 0), \
         mock.patch.object(main.health, "report"), mock.patch.object(main.clv, "capture_closing"), \
         mock.patch.object(main, "resolve_open_bets"), \
         mock.patch.object(main.daily_digest, "remind_awaiting_settlement"), \
         mock.patch.object(main, "send_monthly_digest_if_due"), \
         mock.patch.object(main.daily_digest, "send_daily_digest_if_due"):
        main.main()
    assert order == ["commands", "scan"], order


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
