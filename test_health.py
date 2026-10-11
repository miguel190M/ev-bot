"""Tests for src/health.py (failure / recovery / low-credit alerts).
Run: python test_health.py"""

from datetime import datetime, timedelta, timezone

from src import health

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _HTTPErr(Exception):
    def __init__(self, code):
        super().__init__(f"{code} Client Error")
        self.response = _Resp(code)


def _run(failures, ok, remaining, now, state):
    sent = []
    st = health.report(failures, ok, remaining, now=now, send=sent.append,
                       state=state, persist=False)
    return st, sent


def test_401_alerts_once_then_throttles_then_realerts():
    f = [("americanfootball_nfl", _HTTPErr(401)), ("baseball_mlb", _HTTPErr(401))]
    st, sent = _run(f, 0, None, T0, {})
    assert len(sent) == 1 and "401" in sent[0] and "credits" in sent[0]
    assert "americanfootball_nfl" in sent[0] and st["failing"] is True

    st, sent = _run(f, 0, None, T0 + timedelta(hours=1), st)
    assert sent == []                      # throttled

    st, sent = _run(f, 0, None, T0 + timedelta(hours=7), st)
    assert len(sent) == 1                  # re-alert after 6h


def test_recovery_message_and_state_cleared():
    f = [("baseball_mlb", _HTTPErr(401))]
    st, _ = _run(f, 0, None, T0, {})
    st, sent = _run([], 2, "19996", T0 + timedelta(hours=1), st)
    assert len(sent) == 1 and "working again" in sent[0] and "19996" in sent[0]
    assert st["failing"] is False and "last_alert" not in st
    st, sent = _run([], 2, "19990", T0 + timedelta(hours=2), st)
    assert sent == []                      # no repeat recovery


def test_no_pulls_attempted_changes_nothing():
    f = [("baseball_mlb", _HTTPErr(401))]
    st, _ = _run(f, 0, None, T0, {})
    st, sent = _run([], 0, None, T0 + timedelta(hours=1), st)
    assert sent == [] and st["failing"] is True   # still failing, no false recovery


def test_429_serious_even_if_other_pulls_ok():
    st, sent = _run([("soccer_epl", _HTTPErr(429))], 3, "15000", T0, {})
    assert len(sent) == 1 and "429" in sent[0]


def test_isolated_non_quota_error_with_other_successes_is_ignored():
    st, sent = _run([("tennis_x", _HTTPErr(500))], 2, "15000", T0, {})
    assert sent == [] and not st.get("failing")


def test_all_pulls_failing_with_non_quota_error_alerts():
    st, sent = _run([("tennis_x", _HTTPErr(500))], 0, None, T0, {})
    assert len(sent) == 1


def test_low_credit_levels_fire_once_each_and_rearm():
    st, sent = _run([], 1, "1900", T0, {})
    assert len(sent) == 1 and "1900" in sent[0]
    st, sent = _run([], 1, "1800", T0 + timedelta(hours=1), st)
    assert sent == []
    st, sent = _run([], 1, "450", T0 + timedelta(hours=2), st)
    assert len(sent) == 1 and "450" in sent[0]
    st, sent = _run([], 1, "20000", T0 + timedelta(days=20), st)   # plan renewed
    assert sent == [] and st["low_warned"] == []
    st, sent = _run([], 1, "1500", T0 + timedelta(days=40), st)
    assert len(sent) == 1                  # re-armed


def test_send_failure_does_not_raise_and_retries_next_run():
    def boom(_):
        raise RuntimeError("telegram down")
    f = [("baseball_mlb", _HTTPErr(401))]
    st = health.report(f, 0, None, now=T0, send=boom, state={}, persist=False)
    assert st["failing"] is True and "last_alert" not in st
    st, sent = _run(f, 0, None, T0 + timedelta(minutes=30), st)
    assert len(sent) == 1                  # not throttled, since the first never got out


def test_healthy_run_is_silent():
    st, sent = _run([], 4, "19000", T0, {})
    assert sent == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all passed")
