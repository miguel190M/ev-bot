"""Latest head-to-head prices per book, for eyeballing the feed against the real apps.

Each run, for every event inside the scan window that was pulled this run, the
h2h prices of the books we care about (NextBet/PlayUp, SportsBet, Betfair,
Pinnacle) are stored in data/quotes.json. Sports not pulled this run keep their
previous entry until the game starts. `/quotes` prints them (`/quotes nba`,
`/quotes knicks` to filter); /price is already taken by another command.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

BOOKS = ("playup", "sportsbet", "betfair_ex_au", "pinnacle")
LABELS = {"playup": "NextBet", "sportsbet": "SportsBet", "betfair_ex_au": "Betfair", "pinnacle": "Pinnacle"}


def _load() -> dict:
    try:
        d = json.loads(Path(config.QUOTES_FILE).read_text())
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update(store: dict, events_by_sport: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    for sport, events in events_by_sport.items():
        rows = []
        for e in events:
            books, lines = {}, {}
            for bm in e.get("bookmakers", []):
                if bm["key"] not in BOOKS:
                    continue
                for m in bm.get("markets", []):
                    if len(m.get("outcomes", [])) < 2:
                        continue
                    if m["key"] == "h2h":
                        books[bm["key"]] = {o["name"]: o["price"] for o in m["outcomes"]}
                    elif m["key"] in ("totals", "spreads"):     # [name, line, price] per outcome
                        lines.setdefault(bm["key"], {})[m["key"]] = [
                            [o["name"], o.get("point"), o["price"]] for o in m["outcomes"]]
            if books:
                rows.append({"home": e.get("home_team"), "away": e.get("away_team"),
                             "start": e.get("commence_time"), "books": books, "lines": lines})
        if rows:
            store[sport] = {"ts": stamp, "events": rows}
    # drop games that have already started
    for sport in list(store):
        store[sport]["events"] = [r for r in store[sport]["events"] if (r.get("start") or "") > now.strftime("%Y-%m-%dT%H:%M:%SZ")]
        if not store[sport]["events"]:
            del store[sport]
    return store


def record_run(events_by_sport: dict) -> None:
    if not events_by_sport:
        return
    store = update(_load(), events_by_sport)
    Path(config.QUOTES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(config.QUOTES_FILE).write_text(json.dumps(store, indent=1, sort_keys=True))


def _pair(prices: dict, home: str, away: str) -> str:
    if home in prices and away in prices:
        return f"{prices[home]:.2f}/{prices[away]:.2f}"
    return "/".join(f"{v:.2f}" for v in prices.values())


def _lines_text(lines: dict, key: str) -> list[str]:
    """Totals / handicap quotes of one book, e.g. 'Total 222.5: Over 1.91 / Under 1.88'."""
    out = []
    for mk, label in (("spreads", "Line"), ("totals", "Total")):
        outs = lines.get(key, {}).get(mk)
        if not outs:
            continue
        if mk == "totals":
            pt = outs[0][1]
            out.append(f"{label} {pt:g}: " + " / ".join(f"{n} {p:.2f}" for n, _, p in outs))
        else:
            out.append(f"{label}: " + " / ".join(f"{n} {pt:+g} @ {p:.2f}" for n, pt, p in outs))
    return out


def report(filter_text: str | None = None, now: datetime | None = None, limit: int = 40) -> str:
    now = now or datetime.now(timezone.utc)
    store = _load()
    f = (filter_text or "").strip().lower()
    rows = []
    for sport, entry in store.items():
        if not f or f in sport.lower():
            matching = entry["events"]
        else:
            matching = [r for r in entry["events"] if f in f"{r['home']} {r['away']}".lower()]
        age = int((now - datetime.fromisoformat(entry["ts"])).total_seconds() // 60)
        for r in matching:
            rows.append((r["start"], sport, age, r))
    if not rows:
        return ("No stored prices" + (f" matching '{filter_text}'" if f else "") +
                " - they fill in as games come inside the scan window (check again after the next scan).")
    rows.sort(key=lambda x: x[0])
    out = ["Latest feed prices (home/away), oldest scan shown per sport", ""]
    for start, sport, age, r in rows[:limit]:
        t = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(config_tz()).strftime("%a %H:%M")
        out.append(f"{r['home']} v {r['away']} · {t} · {sport.split('_', 1)[-1]} · scanned {age}m ago")
        for key in BOOKS:
            if key in r["books"]:
                out.append(f"   {LABELS[key]:9} {_pair(r['books'][key], r['home'], r['away'])}")
        if f:       # filtered to one game or sport: also show totals and handicap lines
            for key in BOOKS:
                for t in _lines_text(r.get("lines", {}), key):
                    out.append(f"   {LABELS[key]} - {t}")
        out.append("")
    if len(rows) > limit:
        out.append(f"...{len(rows) - limit} more - add a team or sport to filter, e.g. /quotes knicks")
    return "\n".join(out).strip()


def config_tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Australia/Sydney")
