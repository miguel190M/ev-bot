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
        lines.append(f"Suppressed as too-good-to-be-true (>{config.MAX_EV_PCT:g}% edge): {summary['capped']}")
    return lines
