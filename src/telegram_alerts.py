from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import config, ev_calculator

SYDNEY = ZoneInfo("Australia/Sydney")


def format_message(opp: dict, bet_id: str | None = None) -> str:
    dt_utc = datetime.fromisoformat(opp["commence_time"].replace("Z", "+00:00"))
    dt_syd = dt_utc.astimezone(SYDNEY)
    matchup = f"{opp['away_team']} @ {opp['home_team']}" if opp.get("away_team") else opp.get("home_team", "")
    bet_footer = f"\n\nPlaced it? Log it: /bet {bet_id} <stake>" if bet_id else ""
    commission = opp.get("commission", 0.0)
    commission_note = f"\n(edge is net of {commission * 100:.0f}% {opp['bookmaker_title']} commission)" if commission > 0 else ""
    market_key = opp.get("market_key", "h2h")
    market_line = f"Market: {market_key.capitalize()}\n" if market_key != "h2h" else ""
    disagree_note = ""
    if opp.get("sharp_disagreement") and opp.get("sharp_probability") and opp.get("consensus_probability"):
        disagree_note = (f"\n⚠️ Low confidence: Pinnacle fair ~{1 / opp['sharp_probability']:.2f} vs soft-book "
                         f"median ~{1 / opp['consensus_probability']:.2f} (edge uses the lower probability)")
    return (
        f"🎯 +EV Bet Found ({opp['ev_pct']}% edge)\n"
        f"Sport: {opp['sport_key']}\n"
        f"Event: {matchup}\n"
        f"Start: {dt_syd.strftime('%a %d %b, %I:%M%p %Z')}\n"
        f"{market_line}"
        f"Book: {opp['bookmaker_title']}\n"
        f"Pick: {opp['outcome']} @ {opp['price']}\n"
        f"Fair odds: ~{opp['fair_odds']} ({ev_calculator.describe_anchor(opp)})"
        f"{disagree_note}"
        f"{commission_note}"
        f"{bet_footer}"
    )


def send_alert(opp: dict, bet_id: str | None = None):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("Telegram not configured - would have sent:\n" + format_message(opp, bet_id))
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": format_message(opp, bet_id),
    }, timeout=15)
    resp.raise_for_status()
