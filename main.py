"""
Positive-EV sports bet scanner.

Runs frequently and cheaply: for each sport, it first checks (for free)
whether anything is starting within SCAN_WINDOW_HOURS. Only sports with
something imminent get the paid /odds call - so a run on a quiet afternoon
costs almost nothing, and coverage gets dense automatically as game time
approaches, instead of hoping a fixed clock time lines up with kickoff.

Required env vars: ODDS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Optional env vars: EV_THRESHOLD (default 0.03), MIN_BOOKS (default 3),
                    SCAN_WINDOW_HOURS (default 3), ODDS_REGION (default au)
"""
import sys
from datetime import datetime, timezone

from src import config, odds_fetcher, ev_calculator, state, telegram_alerts, scheduling


def main():
    if not config.ODDS_API_KEY:
        print("ERROR: ODDS_API_KEY not set.")
        sys.exit(1)

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
        print(f"  {sport_key}: something starting within {config.SCAN_WINDOW_HOURS}h - "
              f"pulled odds ({len(events)} events, {used} credits used, {remaining} remaining)")
        for event in events:
            all_opportunities.extend(ev_calculator.find_positive_ev(event))

    if skipped:
        print(f"\nSkipped (nothing starting within {config.SCAN_WINDOW_HOURS}h, no credits spent): {skipped}")

    print(f"\nFound {len(all_opportunities)} +EV opportunities >= {config.EV_THRESHOLD * 100:.1f}% edge")
    print(f"Total credits used this run: {total_credits_used}")

    st = state.load_state()
    now_iso = datetime.now(timezone.utc).isoformat()
    state.prune_expired(st, now_iso)
    fresh = state.filter_new_or_changed(all_opportunities, st)

    print(f"{len(fresh)} are new or meaningfully changed - alerting on those")
    for opp in sorted(fresh, key=lambda o: -o["ev_pct"]):
        telegram_alerts.send_alert(opp)
        print(f"  Alerted: {opp['bookmaker_title']} {opp['outcome']} @ {opp['price']} ({opp['ev_pct']}% EV)")

    state.save_state(st)


if __name__ == "__main__":
    main()
