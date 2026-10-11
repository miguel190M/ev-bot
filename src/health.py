"""Make Odds API problems visible.

A failed paid /odds pull used to be swallowed (printed to the Actions log
only), so running out of credits meant days of silent "no value bets". This
module sends Telegram messages for:
  - pulls failing (401 = out of credits / bad key, 429 = rate limited, or
    every attempted pull failing), repeated at most every HEALTH_REALERT_HOURS
  - recovery once pulls succeed again
  - low credits, once per level (see config.HEALTH_LOW_CREDIT_LEVELS)

State lives in data/health_state.json (committed by the workflow like the
other data files).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config, telegram_commands


def load_state() -> dict:
    p = Path(config.HEALTH_STATE_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(st: dict):
    p = Path(config.HEALTH_STATE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=2, sort_keys=True))


def status_code(exc: Exception):
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


def describe(failures: list) -> str:
    """failures: list of (sport_key, exception)."""
    codes = {status_code(e) for _, e in failures}
    sports = ", ".join(sorted({s for s, _ in failures}))
    if 401 in codes:
        why = ("HTTP 401 - usually out of Odds API credits (or the ODDS_API_KEY "
               "secret is wrong/revoked)")
    elif 429 in codes:
        why = "HTTP 429 - Odds API rate limit hit"
    else:
        why = f"errors: {', '.join(sorted({type(e).__name__ + (' ' + str(status_code(e)) if status_code(e) else '') for _, e in failures}))}"
    return f"{why}\nFailed sports: {sports}"


def is_serious(failures: list, pulls_ok: int) -> bool:
    """Alert on quota/auth errors, or when every attempted pull failed."""
    if not failures:
        return False
    if any(status_code(e) in (401, 429) for _, e in failures):
        return True
    return pulls_ok == 0


def _hours_since(iso: str, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds() / 3600
    except (ValueError, TypeError):
        return float("inf")


def _low_credit_check(st: dict, remaining, send) -> None:
    try:
        rem = int(remaining)
    except (TypeError, ValueError):
        return
    if rem > config.HEALTH_LOW_CREDIT_REARM:
        st["low_warned"] = []
        return
    warned = set(st.get("low_warned", []))
    due = [lvl for lvl in config.HEALTH_LOW_CREDIT_LEVELS if rem <= lvl and lvl not in warned]
    if due:
        send(f"⚠️ Odds API credits low: {rem} left. Bot will go blind when they hit 0 "
             f"(credits reset on the 1st of the month, or upgrade the plan).")
        warned.update(due)
        st["low_warned"] = sorted(warned)


def report(failures: list, pulls_ok: int, remaining, now: datetime | None = None,
           send=None, state: dict | None = None, persist: bool = True) -> dict:
    """Call once per run after the scan. Returns the updated health state."""
    now = now or datetime.now(timezone.utc)
    send = send or telegram_commands.send_message
    st = load_state() if state is None else state

    def safe_send(text: str) -> bool:
        try:
            send(text)
            return True
        except Exception as e:  # never let an alert failure break the scan
            print(f"Health alert could not be sent: {e}")
            return False

    if is_serious(failures, pulls_ok):
        due = (not st.get("failing")
               or _hours_since(st.get("last_alert", ""), now) >= config.HEALTH_REALERT_HOURS)
        if due:
            sent = safe_send("🚨 Odds pulls are FAILING - the bot can't see odds, so no alerts "
                             f"will fire.\n{describe(failures)}")
            if sent:
                st["last_alert"] = now.isoformat()
        st["failing"] = True
    elif st.get("failing") and pulls_ok > 0:
        safe_send(f"✅ Odds pulls working again ({remaining} credits left).")
        st["failing"] = False
        st.pop("last_alert", None)

    if pulls_ok > 0:
        _low_credit_check(st, remaining, safe_send)

    if persist:
        save_state(st)
    return st
