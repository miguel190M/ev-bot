"""Which bookmakers actually quote which markets in the odds feed.

Every run, for each event inside the scan window, this counts which bookmaker
keys returned which markets (h2h / totals / spreads) per sport, plus how many
events carried each market at all. The totals are cumulative (data/book_coverage.json,
committed by the workflow with the other data files), so after a few days
/books shows e.g. whether PlayUp (= NextBet) really prices NBA totals.

Counts are event-scan observations (the same event is counted on every run that
scans it), so read them as ratios, not as numbers of games.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config


def _load() -> dict:
    try:
        data = json.loads(Path(config.COVERAGE_FILE).read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update(cov: dict, events_by_sport: dict, now: datetime | None = None) -> dict:
    """Fold one run's events ({sport_key: [event, ...]}) into the cumulative coverage dict."""
    now = (now or datetime.now(timezone.utc)).isoformat()
    cov.setdefault("since", now)
    cov["runs"] = cov.get("runs", 0) + 1
    cov["updated"] = now
    books, slate = cov.setdefault("books", {}), cov.setdefault("slate", {})
    for sport, events in events_by_sport.items():
        for event in events:
            seen_markets = set()
            for bm in event.get("bookmakers", []):
                b = books.setdefault(bm["key"], {"title": bm.get("title", bm["key"]), "first_seen": now, "sports": {}})
                b["last_seen"] = now
                for m in bm.get("markets", []):
                    if len(m.get("outcomes", [])) < 2:
                        continue
                    seen_markets.add(m["key"])
                    sm = b["sports"].setdefault(sport, {})
                    sm[m["key"]] = sm.get(m["key"], 0) + 1
            for mk in seen_markets:
                s = slate.setdefault(sport, {})
                s[mk] = s.get(mk, 0) + 1
    return cov


def record_run(events_by_sport: dict) -> None:
    if not events_by_sport:
        return
    cov = update(_load(), events_by_sport)
    Path(config.COVERAGE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(config.COVERAGE_FILE).write_text(json.dumps(cov, indent=1, sort_keys=True))


def _key_for(name: str, books: dict) -> str | None:
    """Resolve what the user typed (a key, a title, or NextBet for playup) to a feed key."""
    n = name.strip().lower()
    for k, b in books.items():
        if n in (k.lower(), (b.get("title") or "").lower()):
            return k
    for k, (alias, title) in config.BOOK_KEY_ALIASES.items():
        if n in (alias.lower(), title.lower(), k.lower()) and k in books:
            return k
    return None


def _book_lines(cov: dict, key: str) -> list[str]:
    b, slate = cov["books"][key], cov.get("slate", {})
    shown = config.BOOK_KEY_ALIASES.get(key, (key, b.get("title", key)))[1]
    head = shown + (f" (feed key: {key})" if shown.lower() != key.lower() else "")
    totals = {}                                   # market -> [events book quoted, events slate carried]
    for sport, mk in b["sports"].items():
        for m, n in mk.items():
            t = totals.setdefault(m, [0, 0])
            t[0] += n
            t[1] += slate.get(sport, {}).get(m, 0)
    parts = [f"{m} {n}/{d} ({100 * n / d:.0f}%)" for m, (n, d) in sorted(totals.items()) if d]
    sports = sorted(b["sports"])
    out = [f"{head}: " + (" · ".join(parts) if parts else "no markets seen")]
    out.append(f"   sports: {', '.join(sports) if sports else '-'}")
    out.append(f"   last seen {b.get('last_seen', '?')[:16].replace('T', ' ')} UTC")
    return out


def report(book: str | None = None) -> str:
    cov = _load()
    if not cov.get("books"):
        return "No coverage data yet - it builds up as scans run (first data after the next scan)."
    books = cov["books"]
    lines = [f"Bookmaker coverage since {cov.get('since', '?')[:10]} ({cov.get('runs', 0)} runs)",
             "Share of scanned events each book quoted, per market:", ""]
    if book:
        key = _key_for(book, books)
        if not key:
            return lines[0] + f"\n\nNo book matching '{book}' has appeared in the feed yet."
        return "\n".join(lines + _book_lines(cov, key))
    want = [k for k in books if k in config.BETTABLE_BOOKS or k in config.BOOK_KEY_ALIASES]
    for k in sorted(want):
        lines += _book_lines(cov, k) + [""]
    missing = [b for b in config.BETTABLE_BOOKS if b not in books and
               not any(alias == b and k in books for k, (alias, _) in config.BOOK_KEY_ALIASES.items())]
    for b in missing:
        lines.append(f"{b}: never seen in the feed")
    lines.append("Other books: /books <name>, e.g. /books pinnacle")
    return "\n".join(lines).strip()
