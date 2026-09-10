"""
Positive-EV sports bet scanner, with bet tracking.

Each run does three things:
  1. Scan for +EV opportunities (credit-aware - see scheduling.py) and alert
     on new/changed ones. Every alert includes a short id.
  2. Check Telegram for any /bet or /stats commands you sent back, and act
     on them (log a bet, or reply with a running ROI summary).
  3. For any open bet whose game should have finished by now, pull the
     final score and resolve it automatically - won/lost/void plus profit.

Skips the entire run (no credits, no Telegram polling) during the
configured Sydney-local sleep window.

Required env vars: ODDS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Optional env vars: EV_THRESHOLD (default 0.03), MIN_BOOKS (default 3),
                    SCAN_WINDOW_HOURS (default 3), ODDS_REGION (default au),
                    SLEEP_START_HOUR / SLEEP_END_HOUR (default 1 / 7)
"""
import sys
from datetime import datetime, timedelta, timezone

from src import (
    config, odds_fetcher, ev_calculator, state, telegram_alerts,
    scheduling, bets, scores, telegram_commands,
)

RESOLUTION_BUFFER_HOURS = 4  # wait this long after commence_time before trying to resolve


def run_scan(candidates: dict) -> int:
    """Existing EV scan + alerting. Registers each fresh alert as a bet
    candidate so it can be referenced by /bet later. Returns credits used."""
    print("Fetching active sports (including in-season tennis tournaments)...")
    sports_to_scan = odds_fetcher.get_sports_to_scan()
    print(f"Considering {len(sports_to_scan)} sport keys: {sports_to_scan}\n")

    all_opportunities = []
    total_credits_used = 0
    skipped = []

    for sport_key in sports_to_scan:
        try:
            events_meta = odds_fetcher.get_events(sport_key)  # free
        except Exception as e:
            print(f"  {sport_key}: events check failed ({e}), skipping")
            continue

        if not scheduling.starting_soon(events_meta, config.SCAN_WINDOW_HOURS):
            skipped.append(sport_key)
            continue

        try:
            events, remaining, used = odds_fetcher.get_odds(sport_key)  # costs credits
        except Exception as e:
            print(f"  {sport_key}: odds fetch failed ({e}), skipping")
            continue

        total_credits_used += int(used or 0)
        near_term = scheduling.filter_starting_soon(events, config.SCAN_WINDOW_HOURS)
        print(f"  {sport_key}: something starting within {config.SCAN_WINDOW_HOURS}h - "
              f"pulled odds ({len(events)} events returned, {len(near_term)} within window, "
              f"{used} credits used, {remaining} remaining)")
        for event in near_term:
            all_opportunities.extend(ev_calculator.find_positive_ev(event))

    if skipped:
        print(f"\nSkipped (nothing starting within {config.SCAN_WINDOW_HOURS}h, no credits spent): {skipped}")

    print(f"\nFound {len(all_opportunities)} +EV opportunities >= {config.EV_THRESHOLD * 100:.1f}% edge")

    st = state.load_state()
    now_iso = datetime.now(timezone.utc).isoformat()
    state.prune_expired(st, now_iso)
    fresh = state.filter_new_or_changed(all_opportunities, st)

    print(f"{len(fresh)} are new or meaningfully changed - alerting on those")
    for opp in sorted(fresh, key=lambda o: -o["ev_pct"]):
        bet_id = bets.register_candidate(opp, candidates)
        telegram_alerts.send_alert(opp, bet_id)
        print(f"  Alerted [{bet_id}]: {opp['bookmaker_title']} {opp['outcome']} @ {opp['price']} ({opp['ev_pct']}% EV)")

    state.save_state(st)
    return total_credits_used


def process_commands(candidates: dict, bet_ledger: dict):
    """Handle any /bet or /stats messages sent back since the last run."""
    try:
        messages = telegram_commands.get_new_messages()
    except Exception as e:
        print(f"Telegram command check failed: {e}")
        return

    if not messages:
        print("No new Telegram commands.")
        return

    for text in messages:
        print(f"  Command received: {text}")
        parsed = telegram_commands.parse_bet_command(text)
        if parsed:
            sid, stake = parsed
            opp = candidates.get(sid)
            if not opp:
                telegram_commands.send_message(
                    f"Couldn't find an alert with id '{sid}' - it may have expired "
                    f"(candidates drop off once the event starts) or been mistyped."
                )
                continue
            bet_id, bet = bets.place_bet(sid, stake, opp, bet_ledger)
            matchup = f"{bet.get('away_team')} @ {bet.get('home_team')}" if bet.get("away_team") else bet.get("home_team", "")
            telegram_commands.send_message(
                f"✅ Logged: ${stake:g} on {bet['outcome']} @ {bet['price']} ({matchup}). "
                f"I'll let you know once it resolves."
            )
            print(f"    -> Logged bet {bet_id}: ${stake} on {bet['outcome']} @ {bet['price']}")
        elif telegram_commands.is_stats_command(text):
            s = bets.compute_stats(bet_ledger)
            telegram_commands.send_message(
                f"📊 Bet stats\n"
                f"Resolved: {s['resolved_count']} ({s['wins']}W-{s['losses']}L)\n"
                f"Open: {s['open_count']}\n"
                f"Staked: ${s['total_staked']:g}\n"
                f"Profit: ${s['total_profit']:g}\n"
                f"ROI: {s['roi_pct']}%"
            )
            print(f"    -> Replied with stats: {s}")


def resolve_open_bets(bet_ledger: dict):
    """For open bets old enough that their game should have finished, pull
    the final score and resolve won/lost/void + profit automatically."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=RESOLUTION_BUFFER_HOURS)

    eligible_sports = set()
    for bet in bet_ledger.values():
        if bet["status"] != "open":
            continue
        commence = datetime.fromisoformat(bet["commence_time"].replace("Z", "+00:00"))
        if commence <= cutoff:
            eligible_sports.add(bet["sport_key"])

    if not eligible_sports:
        print("No open bets old enough to resolve yet.")
        return

    for sport_key in eligible_sports:
        try:
            score_events = scores.get_scores(sport_key, days_from=3)
        except Exception as e:
            print(f"  Scores fetch failed for {sport_key}: {e}")
            continue
        by_id = {e["id"]: e for e in score_events}

        for bet_id, bet in bet_ledger.items():
            if bet["status"] != "open" or bet["sport_key"] != sport_key:
                continue
            score_event = by_id.get(bet["event_id"])
            if not score_event:
                continue
            final = scores.extract_final_scores(score_event)
            if not final:
                continue
            if bets.resolve_bet(bet, final):
                matchup = f"{bet.get('away_team')} @ {bet.get('home_team')}" if bet.get("away_team") else bet.get("home_team", "")
                verdict = {"won": "✅ WON", "lost": "❌ LOST", "void": "➖ VOID"}[bet["status"]]
                telegram_commands.send_message(
                    f"{verdict}: {bet['outcome']} @ {bet['price']} ({matchup})\n"
                    f"Profit: ${bet['profit']:g}"
                )
                print(f"  Resolved {bet_id}: {bet['status']} (${bet['profit']})")


def main():
    if scheduling.is_sleep_window(config.SLEEP_START_HOUR, config.SLEEP_END_HOUR):
        local_now = datetime.now(timezone.utc).astimezone(scheduling.SYDNEY)
        print(f"In sleep window ({config.SLEEP_START_HOUR}:00-{config.SLEEP_END_HOUR}:00 Sydney time, "
              f"currently {local_now.strftime('%I:%M %p %Z')}) - skipping this run entirely, no credits spent.")
        return

    if not config.ODDS_API_KEY:
        print("ERROR: ODDS_API_KEY not set.")
        sys.exit(1)

    candidates = bets.load_candidates()
    bet_ledger = bets.load_bets()

    credits_used = run_scan(candidates)

    now_iso = datetime.now(timezone.utc).isoformat()
    bets.prune_candidates(candidates, now_iso)
    bets.save_candidates(candidates)

    process_commands(candidates, bet_ledger)
    resolve_open_bets(bet_ledger)
    bets.save_bets(bet_ledger)

    print(f"\nTotal credits used this run: {credits_used}")


if __name__ == "__main__":
    main()
