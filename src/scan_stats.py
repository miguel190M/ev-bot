"""Per-run scan statistics, so a quiet week is explainable.

Each run records how many market checks it made, how many were priced against
the sharp book (Pinnacle), and the "closest call" - the outcome whose edge
came nearest to (or furthest past) its alert threshold. The 9am daily digest
summarises the last 24h from data/scan_stats.json (committed by the workflow
like the other data files, pruned to the last 48h).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

KEEP_HOURS = 48


def new_stats() -> dict:
    return {"markets": 0, "markets_sharp": 0, "outcomes": 0, "capped": 0, "best": None}


def note_candidate(stats: dict, cand: dict) -> None:
    """Keep the outcome with the largest (edge - threshold) gap seen so far."""
    best = stats.get("best")
    if best is None or cand["gap"] > best["gap"]:
        stats["best"] = cand


def _load() -> list:
    p = Path(config.SCAN_STATS_FILE)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def record_run(stats: dict, now: datetime | None = None) -> None:
    """Append this run's stats (skipped if the run evaluated nothing)."""
    if not stats.get("markets"):
        return
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=KEEP_HOURS)).isoformat()
    runs = [r for r in _load() if r.get("ts", "") >= cutoff]
    runs.append({"ts": now.isoformat(), **stats})
    p = Path(config.SCAN_STATS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(runs, indent=1))


def summarize(now: datetime | None = None, hours: float = 24) -> dict | None:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    runs = [r for r in _load() if r.get("ts", "") >= since]
    if not runs:
        return None
    best = None
    for r in runs:
        b = r.get("best")
        if b and (best is None or b["gap"] > best["gap"]):
            best = b
    return {
        "runs": len(runs),
        "markets": sum(r.get("markets", 0) for r in runs),
        "markets_sharp": sum(r.get("markets_sharp", 0) for r in runs),
        "capped": sum(r.get("capped", 0) for r in runs),
        "best": best,
    }


def format_lines(summary: dict | None) -> list[str]:
    if not summary:
        return []
    pct = round(100 * summary["markets_sharp"] / summary["markets"]) if summary["markets"] else 0
    lines = [f"Scans: {summary['runs']} runs · {summary['markets']} market checks ({pct}% priced vs Pinnacle)"]
    b = summary.get("best")
    if b:
        tail = "needed" if b["gap"] < 0 else "threshold (alerted)"
        lines.append(
            f"Closest call: {b['outcome']} @ {b['price']} ({b['book']}) - {b['matchup']}\n"
            f"   edge {b['ev_pct']:+.1f}% vs {b['threshold_pct']:.1f}% {tail}"
        )
    if summary.get("capped"):
        lines.append(f"Suppressed as too-good-to-be-true (>{config.MAX_EV_PCT:g}% edge): {summary['capped']} (see /suppressed)")
    return lines


# ---- picks suppressed by the MAX_EV_PCT cap ---------------------------------

def _load_suppressed() -> dict:
    p = Path(config.SUPPRESSED_FILE)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def record_suppressed(picks: list, now: datetime | None = None) -> None:
    """Merge this run's capped picks into data/suppressed_picks.json (one entry
    per pick, with first/last seen, how many runs it showed up in, and its biggest
    edge). Entries not seen for KEEP_HOURS are dropped."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = (now - timedelta(hours=KEEP_HOURS)).isoformat()
    store = {k: v for k, v in _load_suppressed().items() if v.get("last_seen", "") >= cutoff}
    for pk in picks:
        key = f"{pk['sport_key']}|{pk['matchup']}|{pk['market']}|{pk['outcome']}|{pk['book']}"
        cur = store.get(key)
        if cur is None:
            store[key] = {**pk, "first_seen": now_iso, "last_seen": now_iso, "seen": 1, "max_ev_pct": pk["ev_pct"]}
        else:
            max_ev = max(cur.get("max_ev_pct", 0), pk["ev_pct"])
            store[key] = {**cur, **pk, "first_seen": cur["first_seen"], "last_seen": now_iso,
                          "seen": cur.get("seen", 1) + 1, "max_ev_pct": max_ev}
    p = Path(config.SUPPRESSED_FILE)
    if store or p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(store, indent=1, sort_keys=True))


def suppressed_report(now: datetime | None = None, hours: float = 24, top: int = 10) -> str:
    """Text for /suppressed: which picks tripped the too-good-to-be-true cap."""
    from collections import Counter
    from .daily_digest import _sport_label  # label helper (lazy: avoids a circular import)
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    picks = [v for v in _load_suppressed().values() if v.get("last_seen", "") >= since]
    if not picks:
        return (f"🚫 No picks were suppressed as too-good-to-be-true (>{config.MAX_EV_PCT:g}% edge) "
                f"in the last {hours:g}h that I have details for (details are recorded from this feature onwards).")
    picks.sort(key=lambda v: -v["max_ev_pct"])
    by_sport = Counter(_sport_label(v["sport_key"]) for v in picks)
    by_anchor = Counter("vs Pinnacle" if v["anchor"] != "retail_consensus" else "vs soft-book median" for v in picks)
    by_book = Counter(v["book"] for v in picks)
    lines = [f"🚫 Suppressed as too-good-to-be-true (>{config.MAX_EV_PCT:g}% edge) - last {hours:g}h",
             f"{len(picks)} unique picks (a pick can show up in many scans)",
             "By sport: " + " · ".join(f"{k} {n}" for k, n in by_sport.most_common()),
             "Priced: " + " · ".join(f"{k} {n}" for k, n in by_anchor.most_common()),
             "Book: " + " · ".join(f"{k} {n}" for k, n in by_book.most_common()),
             "", f"Biggest {min(top, len(picks))} by edge:"]
    for i, v in enumerate(picks[:top], 1):
        ref = f"Pinnacle {v['sharp_odds']}" if v.get("sharp_odds") else f"median {v.get('consensus_odds')}"
        both = ""
        if v.get("sharp_odds") and v.get("consensus_odds"):
            both = f", soft-book median {v['consensus_odds']}"
        lines.append(f"{i}. {v['outcome']} @ {v['price']} ({v['book']}) +{v['max_ev_pct']:.0f}% - {v['matchup']}\n"
                     f"   fair {v['fair_odds']} ({ref}{both if v.get('sharp_odds') else ''}) · "
                     f"{_sport_label(v['sport_key'])} · seen {v.get('seen', 1)}x")
    lines += ["", "These are usually a stale book price or a bad reference line - check the price is still live",
              "before trusting any of them. Raise MAX_EV_PCT to let bigger edges alert."]
    return "\n".join(lines)
