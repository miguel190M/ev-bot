"""Once-a-day Telegram report: today's value bets plus a results/bankroll
check-in. Piggybacks on the existing 30-min run (no second workflow) - the
first run on or after DAILY_DIGEST_HOUR Sydney time sends it, and
digest_state.json stops it going out twice in the same day. If the 9am run
is missed or fails, the next run that day catches it.

Credit-aware like the main scan: any sport whose odds were already pulled
by this run's real-time scan is reused for free (the /odds response covers
every upcoming event for that sport, not just the 3h window). Only sports
with something starting inside DAILY_SLATE_HOURS - checked on the free
/events endpoint - cost an extra call.

Caveat baked into the message: edges found 12h+ before kickoff are on
softer, less-settled lines than the ones the real-time scan catches close
to start. Treat the slate as a watchlist; the real-time alert near kickoff
(if the edge survives) is the stronger signal.
"""

from datetime import datetime, timedelta, timezone

from . import config, odds_fetcher, ev_calculator, scheduling, bets, state, telegram_commands

SPORT_LABELS = {
    "basketball_nba": "NBA",
    "americanfootball_nfl": "NFL",
    "aussierules_afl": "AFL",
    "rugbyleague_nrl": "NRL",
    "soccer_epl": "EPL",
}


def _sport_label(sport_key: str) -> str:
    if sport_key.startswith("tennis_"):
        return "Tennis " + sport_key.split("_", 2)[-1].replace("_", " ").title()
    return SPORT_LABELS.get(sport_key, sport_key)


def _matchup(o: dict) -> str:
    return f"{o['away_team']} @ {o['home_team']}" if o.get("away_team") else o.get("home_team", "")


def _find_or_register(opp: dict, candidates: dict) -> str:
    """Reuse the id of an identical opportunity the real-time scan already
    alerted (so the same bet doesn't get two ids), otherwise register it."""
    key = state.make_key(opp)
    for sid, c in candidates.items():
        if state.make_key(c) == key:
            c.update({k: v for k, v in opp.items()})  # refresh to latest price/EV
            return sid
    sid = bets.register_candidate(opp, candidates)
    candidates[sid]["source"] = "daily_digest"
    return sid


def collect_slate(odds_cache: dict, now: datetime) -> list[dict]:
    """All +EV opportunities for events starting within DAILY_SLATE_HOURS."""
    window = config.DAILY_SLATE_HOURS
    opportunities = []
    for sport_key in odds_fetcher.get_sports_to_scan():
        events = odds_cache["events"].get(sport_key)
        if events is None:
            try:
                meta = odds_fetcher.get_events(sport_key)  # free
            except Exception as e:
                print(f"  digest: {sport_key} events check failed ({e})")
                continue
            if not scheduling.starting_soon(meta, window, now):
                continue
            try:
                events, remaining, used = odds_fetcher.get_odds(sport_key)  # paid
            except Exception as e:
                print(f"  digest: {sport_key} odds fetch failed ({e})")
                continue
            odds_cache["events"][sport_key] = events
            odds_cache["remaining"] = remaining
            odds_cache["credits_used"] = odds_cache.get("credits_used", 0) + int(used or 0)
            print(f"  digest: pulled {sport_key} ({used} credits, {remaining} remaining)")
        for event in scheduling.filter_starting_soon(events, window, now):
            opportunities.extend(ev_calculator.find_positive_ev(event))
    return opportunities


def _best_per_pick(opps: list[dict]) -> list[dict]:
    """If both Betfair and Sportsbet flag the same pick, show the better one."""
    best = {}
    for o in opps:
        k = (o["event_id"], o.get("market_key", "h2h"), o["outcome"])
        if k not in best or o["ev_pct"] > best[k]["ev_pct"]:
            best[k] = o
    return sorted(best.values(), key=lambda o: -o["ev_pct"])


def format_digest(slate: list[dict], ids: dict, candidates: dict, bet_ledger: dict,
                  credits_remaining, now: datetime) -> str:
    local = now.astimezone(scheduling.SYDNEY)
    since = (now - timedelta(hours=24)).isoformat()
    lines = [f"📋 Daily value report - {local.strftime('%a %d %b')}", ""]

    # --- Today's slate ---
    shown = slate[: config.DAILY_SLATE_MAX]
    if shown:
        extra = f", top {len(shown)} shown" if len(slate) > len(shown) else ""
        lines.append(f"🎯 Next {config.DAILY_SLATE_HOURS:g}h: {len(slate)} value bet(s){extra}")
        for o in shown:
            start = datetime.fromisoformat(o["commence_time"].replace("Z", "+00:00")).astimezone(scheduling.SYDNEY)
            mkt = "" if o.get("market_key", "h2h") == "h2h" else f" {o['market_key']}"
            lines.append(
                f"[{ids[id(o)]}] {o['outcome']} @ {o['price']} - {o['bookmaker_title']}\n"
                f"   {_sport_label(o['sport_key'])}{mkt} · {_matchup(o)} · {start.strftime('%a %I:%M%p')}\n"
                f"   +{o['ev_pct']}% edge (fair ~{o['fair_odds']}, {o['num_books']} books)"
            )
        lines.append("Early lines - wait for a live alert near kickoff to confirm. Log: /bet <id> <stake>")
    else:
        lines.append(f"🎯 Next {config.DAILY_SLATE_HOURS:g}h: no value bets clear the threshold right now")
    lines.append("")

    # --- Last 24h ---
    alerts_24h = sum(1 for c in candidates.values()
                     if c.get("alerted_at", "") >= since and c.get("source") != "daily_digest")
    resolved_24h = [b for b in bet_ledger.values()
                    if b["status"] in ("won", "lost", "void") and b.get("resolved_at", "") >= since]
    open_bets = [b for b in bet_ledger.values() if b["status"] == "open"]
    lines.append("📈 Last 24h")
    lines.append(f"Live alerts sent: {alerts_24h}")
    if resolved_24h:
        w = sum(b["status"] == "won" for b in resolved_24h)
        l = sum(b["status"] == "lost" for b in resolved_24h)
        v = sum(b["status"] == "void" for b in resolved_24h)
        p = sum(b["profit"] or 0 for b in resolved_24h)
        lines.append(f"Settled: {w}W-{l}L" + (f"-{v}V" if v else "") + f" · {'+' if p >= 0 else '-'}${abs(p):.2f}")
    else:
        lines.append("Settled: none")
    lines.append(f"Open: {len(open_bets)} (${sum(b['stake'] for b in open_bets):g} at risk)")
    lines.append("")

    # --- All-time ---
    s = bets.compute_stats(bet_ledger)
    clv = f" · net CLV {s['avg_net_clv_pct']:+.1f}%" if s.get("avg_net_clv_pct") is not None else ""
    lines.append(f"📊 All-time: {s['wins']}W-{s['losses']}L · ROI {s['roi_pct']}% · "
                 f"${s['total_profit']:g}{clv}")
    if credits_remaining is not None:
        lines.append(f"Odds API credits left: {credits_remaining}")
    return "\n".join(lines)


def send_daily_digest_if_due(candidates: dict, bet_ledger: dict, odds_cache: dict,
                             now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    digest_state = bets.load_digest_state()
    due, today = scheduling.is_daily_digest_due(
        digest_state.get("last_daily_date", ""), config.DAILY_DIGEST_HOUR, now)
    if not due:
        return False

    print(f"\nBuilding daily digest ({today})...")
    slate = _best_per_pick(collect_slate(odds_cache, now))
    ids = {}
    for o in slate:
        sid = _find_or_register(o, candidates)
        candidates[sid].setdefault("alerted_at", now.isoformat())
        ids[id(o)] = sid

    msg = format_digest(slate, ids, candidates, bet_ledger, odds_cache.get("remaining"), now)
    telegram_commands.send_message(msg)

    digest_state["last_daily_date"] = today
    bets.save_digest_state(digest_state)
    print(msg)
    return True
