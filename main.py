"""
Positive-EV sports bet scanner, with bet tracking.

Each run does three things:
  1. Scan for +EV opportunities (credit-aware - see scheduling.py) and alert
     on new/changed ones. Every alert includes a short id.
  2. Check Telegram for any /bet or /stats commands you sent back, and act
     on them (log a bet, or reply with a running ROI summary).
  3. For any open bet whose game should have finished by now, pull the
     final score and resolve it automatically - won/lost/void plus profit.

Required env vars: ODDS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Optional env vars: EV_THRESHOLD_SLOPE / EV_THRESHOLD_INTERCEPT (defaults
                    0.02 / -0.01, giving a scaling threshold rather than a
                    flat one), MIN_BOOKS (default 3),
                    SCAN_WINDOW_HOURS (default 3, dense near-zone checking),
                    FAR_WINDOW_HOURS / FAR_CHECK_INTERVAL_HOURS (default
                    12 / 4, sparse outer-zone checking - see scheduling.py),
                    ODDS_REGION (default au)
"""
import sys
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src import (
    config, odds_fetcher, ev_calculator, state, telegram_alerts,
    scheduling, bets, scores, telegram_commands, daily_digest, breakdown, clv,
)

RESOLUTION_BUFFER_HOURS = 4  # wait this long after commence_time before trying to resolve
FAR_SCAN_STATE_FILE = "data/far_scan_state.json"


def _load_far_scan_state() -> dict:
    p = Path(FAR_SCAN_STATE_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save_far_scan_state(far_scan_state: dict):
    p = Path(FAR_SCAN_STATE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(far_scan_state, indent=2, sort_keys=True))


def run_scan(candidates: dict, bet_ledger: dict, odds_cache: dict) -> int:
    """Existing EV scan + alerting. Registers each fresh alert as a bet
    candidate so it can be referenced by /bet later. Also captures a CLV
    (Closing Line Value) snapshot for any open bet whose event gets
    re-scanned here as kickoff approaches - the last one captured before
    the event starts becomes the closing-line proxy. Returns credits used."""
    print("Fetching active sports (including in-season tennis tournaments)...")
    sports_to_scan = odds_fetcher.get_sports_to_scan()
    print(f"Considering {len(sports_to_scan)} sport keys: {sports_to_scan}\n")

    all_opportunities = []
    total_credits_used = 0
    skipped = []
    seen_bookmakers = {}  # bookmaker_key -> title, across every event fetched this run

    open_bets_by_event = {}
    for bet in bet_ledger.values():
        if bet["status"] == "open":
            open_bets_by_event.setdefault(bet["event_id"], []).append(bet)

    far_scan_state = _load_far_scan_state()

    for sport_key in sports_to_scan:
        try:
            events_meta = odds_fetcher.get_events(sport_key)  # free
        except Exception as e:
            print(f"  {sport_key}: events check failed ({e}), skipping")
            continue

        tier = scheduling.scan_tier(events_meta, config.SCAN_WINDOW_HOURS, config.FAR_WINDOW_HOURS)

        if tier == "none":
            skipped.append(sport_key)
            continue

        if tier == "far":
            if not scheduling.is_far_check_due(far_scan_state.get(sport_key), config.FAR_CHECK_INTERVAL_HOURS):
                skipped.append(f"{sport_key} (far zone, not due for another check yet)")
                continue
            far_scan_state[sport_key] = datetime.now(timezone.utc).isoformat()

        try:
            events, remaining, used = odds_fetcher.get_odds(sport_key)  # costs credits
        except Exception as e:
            print(f"  {sport_key}: odds fetch failed ({e}), skipping")
            continue

        total_credits_used += int(used or 0)
        odds_cache["events"][sport_key] = events  # daily digest reuses this for free
        odds_cache["remaining"] = remaining
        # Evaluate everything within the FULL window of interest, not just
        # the near zone - a far-zone check that then discarded anything
        # beyond SCAN_WINDOW_HOURS would pay for data and throw away the
        # exact event that justified paying for it.
        near_term = scheduling.filter_starting_soon(events, config.FAR_WINDOW_HOURS)
        regions_used = config.get_regions_for_sport(sport_key)
        markets_used = config.get_markets_for_sport(sport_key)
        print(f"  {sport_key}: {tier} zone - "
              f"pulled odds (region={regions_used}, markets={markets_used}, {len(events)} events returned, "
              f"{len(near_term)} within window, {used} credits used, {remaining} remaining)")
        for event in near_term:
            for bm in event.get("bookmakers", []):
                seen_bookmakers[bm["key"]] = bm.get("title", bm["key"])
            for bet in open_bets_by_event.get(event["id"], []):
                fair_odds = ev_calculator.get_reference_fair_odds(event, bet["outcome"], bet.get("market_key", "h2h"))
                if fair_odds:
                    bet["closing_fair_odds"] = fair_odds
            all_opportunities.extend(ev_calculator.find_positive_ev(event))

    _save_far_scan_state(far_scan_state)

    if seen_bookmakers:
        Path("data").mkdir(exist_ok=True)
        Path("data/seen_bookmakers.json").write_text(json.dumps(seen_bookmakers, indent=2, sort_keys=True))
        print(f"\nBookmaker keys seen this run: {seen_bookmakers}")

    if skipped:
        print(f"\nSkipped (no credits spent): {skipped}")

    print(f"\nFound {len(all_opportunities)} +EV opportunities (threshold scales with price - "
          f"e.g. {config.get_ev_threshold(2.0) * 100:.1f}% at odds of 2.0, "
          f"{config.get_ev_threshold(4.0) * 100:.1f}% at odds of 4.0)")

    st = state.load_state()
    now_iso = datetime.now(timezone.utc).isoformat()
    state.prune_expired(st, now_iso)
    fresh = state.filter_new_or_changed(all_opportunities, st)

    print(f"{len(fresh)} are new or meaningfully changed - alerting on those")
    for opp in sorted(fresh, key=lambda o: -o["ev_pct"]):
        bet_id = bets.register_candidate(opp, candidates)
        candidates[bet_id]["alerted_at"] = now_iso
        telegram_alerts.send_alert(opp, bet_id)
        print(f"  Alerted [{bet_id}]: {opp['bookmaker_title']} {opp['outcome']} @ {opp['price']} ({opp['ev_pct']}% EV)")

    state.save_state(st)
    return total_credits_used


def _clv_line(s: dict) -> str:
    if s["avg_clv_pct"] is None:
        return "Avg CLV: not enough data yet"
    line = f"Avg Raw CLV: {s['avg_clv_pct']:+.1f}% (n={s['clv_sample_size']})"
    if s.get("avg_net_clv_pct") is not None:
        line += f"\nAvg Net CLV: {s['avg_net_clv_pct']:+.1f}%"
    return line


def process_commands(candidates: dict, bet_ledger: dict):
    """Handle any /bet, /stats or /breakdown messages sent back since the last run."""
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
        elif (dim := telegram_commands.parse_breakdown_command(text)):
            telegram_commands.send_message(breakdown.build(bet_ledger, dim))
            print(f"    -> Replied with breakdown ({dim})")
        elif telegram_commands.is_stats_command(text):
            s = bets.compute_stats(bet_ledger)
            telegram_commands.send_message(
                f"📊 Bet stats\n"
                f"Resolved: {s['resolved_count']} ({s['wins']}W-{s['losses']}L)\n"
                f"Open: {s['open_count']}\n"
                f"Staked: ${s['total_staked']:g}\n"
                f"Profit: ${s['total_profit']:g}\n"
                f"ROI: {s['roi_pct']}%\n"
                f"{_clv_line(s)}"
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
                bet["resolved_at"] = now.isoformat()
                matchup = f"{bet.get('away_team')} @ {bet.get('home_team')}" if bet.get("away_team") else bet.get("home_team", "")
                verdict = {"won": "✅ WON", "lost": "❌ LOST", "void": "➖ VOID"}[bet["status"]]
                clv_line = ""
                if bet.get("clv_pct") is not None:
                    if bet.get("net_clv_pct") is not None and bet.get("commission", 0.0) > 0:
                        clv_line = f"\nRaw CLV: {bet['clv_pct']:+.1f}% | Net CLV: {bet['net_clv_pct']:+.1f}%"
                    else:
                        clv_line = f"\nCLV: {bet['clv_pct']:+.1f}%"
                telegram_commands.send_message(
                    f"{verdict}: {bet['outcome']} @ {bet['price']} ({matchup})\n"
                    f"Profit: ${bet['profit']:g}"
                    f"{clv_line}"
                )
                print(f"  Resolved {bet_id}: {bet['status']} (${bet['profit']}, CLV={bet.get('clv_pct')}, net={bet.get('net_clv_pct')})")


def send_monthly_digest_if_due(bet_ledger: dict):
    """Send an unprompted /stats-style summary on the 1st of the month
    (Sydney time), so you get a running check-in without having to
    remember to ask for one."""
    digest_state = bets.load_digest_state()
    last_sent = digest_state.get("last_sent_month", "")
    due, current_month = scheduling.is_monthly_digest_due(last_sent)
    if not due:
        return

    s = bets.compute_stats(bet_ledger)
    telegram_commands.send_message(
        f"📅 Monthly summary ({current_month})\n"
        f"Resolved: {s['resolved_count']} ({s['wins']}W-{s['losses']}L, {s['voids']} void)\n"
        f"Open: {s['open_count']}\n"
        f"Staked: ${s['total_staked']:g}\n"
        f"Profit: ${s['total_profit']:g}\n"
        f"ROI: {s['roi_pct']}%\n"
        f"{_clv_line(s)}"
    )
    digest_state["last_sent_month"] = current_month
    bets.save_digest_state(digest_state)
    print(f"Sent monthly digest for {current_month}: {s}")


def main():
    if scheduling.is_sleep_window(config.SLEEP_START_HOUR, config.SLEEP_END_HOUR):
        local_now = datetime.now(timezone.utc).astimezone(scheduling.SYDNEY)
        print(f"In sleep window ({config.SLEEP_START_HOUR}:00-{config.SLEEP_END_HOUR}:00 Sydney time, "
              f"currently {local_now.strftime('%I:%M %p %Z')}) - no scanning or alerts.")
        # Still take closing snapshots for bets kicking off overnight (e.g.
        # EPL), otherwise those never get CLV. Costs nothing unless an open
        # bet starts within CLV_CAPTURE_MINUTES.
        if config.ODDS_API_KEY:
            ledger = bets.load_bets()
            cache = {"events": {}, "remaining": None, "credits_used": 0}
            used = clv.capture_closing(ledger, cache)
            bets.save_bets(ledger)
            print(f"Credits used: {used}")
        return

    if not config.ODDS_API_KEY:
        print("ERROR: ODDS_API_KEY not set.")
        sys.exit(1)

    candidates = bets.load_candidates()
    bet_ledger = bets.load_bets()

    odds_cache = {"events": {}, "remaining": None, "credits_used": 0}
    credits_used = run_scan(candidates, bet_ledger, odds_cache)

    # Give any /bet command first crack at matching a candidate before
    # pruning runs - belt-and-braces alongside the grace period in
    # prune_candidates, so a same-run race can't cost a valid match either.
    process_commands(candidates, bet_ledger)

    # After commands, so a bet logged this run gets a snapshot straight away.
    clv.capture_closing(bet_ledger, odds_cache)

    now_iso = datetime.now(timezone.utc).isoformat()
    bets.prune_candidates(candidates, now_iso)
    bets.save_candidates(candidates)

    resolve_open_bets(bet_ledger)
    send_monthly_digest_if_due(bet_ledger)
    try:
        daily_digest.send_daily_digest_if_due(candidates, bet_ledger, odds_cache)
    except Exception as e:
        print(f"Daily digest failed (will retry next run): {e}")
    bets.save_candidates(candidates)  # digest may have registered slate ids
    bets.save_bets(bet_ledger)

    print(f"\nTotal credits used this run: {credits_used + odds_cache['credits_used']}")


if __name__ == "__main__":
    main()
