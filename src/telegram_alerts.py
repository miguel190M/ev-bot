from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import config, ev_calculator

SYDNEY = ZoneInfo("Australia/Sydney")


def format_message(opp: dict, bet_id: str | None = None) -> str:
    dt_utc = datetime.fromisoformat(opp["commence_time"].replace("Z", "+00:00"))
    dt_syd = dt_utc.astimezone(SYDNEY)
    matchup = f"{opp['away_team']} @ {opp['home_team']}" if opp.get("away_team") else opp.get("home_team", "")
    stake = opp.get("suggested_stake") or 0
    stake_line = (f"\nSuggested stake: ${stake:g} (¼-Kelly on ~{config.EDGE_SHRINK * 100:.0f}% of the edge, "
                  f"bankroll ${config.BANKROLL:g})") if stake else ""
    stake_arg = f"{stake:g}" if stake else "<stake>"
    bet_footer = f"\n\nPlaced it? Log it: /bet {bet_id} {stake_arg}  (got a different price? add @<price>, e.g. /bet {bet_id} {stake_arg} @1.65)" if bet_id else ""
    commission = opp.get("commission", 0.0)
    commission_note = f"\n(edge is net of {commission * 100:.0f}% {opp['bookmaker_title']} commission)" if commission > 0 else ""
    market_key = opp.get("market_key", "h2h")
    market_line = f"Market: {market_key.capitalize()}\n" if market_key != "h2h" else ""
    disagree_note = ""
    if opp.get("sharp_disagreement") and opp.get("sharp_probability") and opp.get("consensus_probability"):
        disagree_note = (f"\n⚠️ Low confidence: Pinnacle fair ~{1 / opp['sharp_probability']:.2f} vs soft-book "
                         f"median ~{1 / opp['consensus_probability']:.2f} (edge uses the lower probability)")
    arb = opp.get("arb")
    if arb:
        held = f"{arb['held_outcome']}" + (f" @ {arb['held_price']}" if arb.get("held_price") else "")
        return (
            f"🔒 ARBITRAGE - hedge your open bet (locks +${arb['profit']:.2f}, +{arb['profit_pct']:.1f}%)\n"
            f"Event: {matchup}\n"
            f"Start: {dt_syd.strftime('%a %d %b, %I:%M%p %Z')}\n"
            f"{market_line}"
            f"You hold: {held} ({arb['held_book']}) ${arb['held_stake']:g}\n"
            f"Bet now: {opp['outcome']} @ {opp['price']} at {opp['bookmaker_title']}\n"
            f"Best size: ${arb['stake']:.2f}  (equal ${arb['payout']:.2f} back whichever side wins)\n"
            f"Total outlay ${arb['outlay']:.2f} -> guaranteed profit ${arb['profit']:.2f} ({arb['profit_pct']:.1f}%)"
            f"{commission_note}"
            + (f"\n\nPlaced it? Log it: /bet {bet_id} {arb['stake']:.2f}  (different price? add @<price>)" if bet_id else "")
        )
    large_note = ""
    header = f"🎯 +EV Bet Found ({opp['ev_pct']}% edge)"
    if opp.get("large_edge"):
        header = f"⚠️ LARGE EDGE - may be too good to be true ({opp['ev_pct']}% edge)"
        large_note = (f"\n⚠️ Edge is above the {config.MAX_EV_PCT:g}% sanity cap - often a stale price or a bad "
                      f"reference line. Check the price is still live before betting. Tracked separately as a large-edge bet.")
    return (
        f"{header}\n"
        f"Sport: {opp['sport_key']}\n"
        f"Event: {matchup}\n"
        f"Start: {dt_syd.strftime('%a %d %b, %I:%M%p %Z')}\n"
        f"{market_line}"
        f"Book: {opp['bookmaker_title']}\n"
        f"Pick: {opp['outcome']} @ {opp['price']}\n"
        f"Fair odds: ~{opp['fair_odds']} ({ev_calculator.describe_anchor(opp)})"
        f"{disagree_note}"
        f"{large_note}"
        f"{commission_note}"
        f"{stake_line}"
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
