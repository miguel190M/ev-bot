from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import config

SYDNEY = ZoneInfo("Australia/Sydney")


def format_message(opp: dict, bet_id: str | None = None) -> str:
    dt_utc = datetime.fromisoformat(opp["commence_time"].replace("Z", "+00:00"))
    dt_syd = dt_utc.astimezone(SYDNEY)
    matchup = f"{opp['away_team']} @ {opp['home_team']}" if opp.get("away_team") else opp.get("home_team", "")
    anchor_label = "Betfair Exchange (back/lay mid)" if opp["anchor"] == "betfair_exchange" \
        else f"retail median consensus, {opp['num_books']} books"
    confidence_note = "" if opp["anchor"] == "betfair_exchange" else "\n⚠️ lower confidence - no Betfair line available for this one"
    bet_footer = f"\n\nPlaced it? Log it: /bet {bet_id} <stake>" if bet_id else ""
    return (
        f"🎯 +EV Bet Found ({opp['ev_pct']}% edge)\n"
        f"Sport: {opp['sport_key']}\n"
        f"Event: {matchup}\n"
        f"Start: {dt_syd.strftime('%a %d %b, %I:%M%p %Z')}\n"
        f"Book: {opp['bookmaker_title']}\n"
        f"Pick: {opp['outcome']} @ {opp['price']}\n"
        f"Fair odds: ~{opp['fair_odds']} (via {anchor_label})"
        f"{confidence_note}"
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
