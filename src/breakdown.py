"""/breakdown: ROI and CLV split by segment, so you can see which slices of
the bot's output actually carry an edge.

Read CLV first. It's about price movement, not outcome, so it stabilises in
dozens of bets where ROI needs hundreds - a segment with consistently
negative net CLV is losing to the market regardless of what its ROI says so
far. Segments under MIN_N settled bets are shown but flagged as too small
to read anything into.
"""
from . import bets as bets_mod

MIN_N = 20


def _sport(b):
    key = b.get("sport_key", "?")
    if key.startswith("tennis_"):  # one bucket per tour, not per tournament
        return "Tennis " + key.split("_")[1].upper()
    from .daily_digest import _sport_label
    return _sport_label(key)


def _edge(b):
    e = b.get("ev_pct") or 0
    return "<3%" if e < 3 else "3-5%" if e < 5 else "5-8%" if e < 8 else "8%+"


def _lead(b):
    h = b.get("lead_hours")
    if h is None:
        return "unknown"
    return "<3h" if h < 3 else "3-12h" if h < 12 else "12h+"


def _source(b):
    return "digest" if b.get("source") == "daily_digest" else "live"  # pre-tagging bets were all live


DIMENSIONS = {
    "sport": ("Sport", _sport),
    "book": ("Book", lambda b: b.get("bookmaker_title", "?")),
    "source": ("Source", _source),
    "edge": ("Edge at alert", _edge),
    "lead": ("Taken before kickoff", _lead),
    "market": ("Market", lambda b: b.get("market_key", "h2h")),
}


def _row(label: str, group: list[dict]) -> str:
    decided = [b for b in group if b["status"] in ("won", "lost")]
    w = sum(b["status"] == "won" for b in decided)
    staked = sum(b["stake"] for b in decided)
    profit = sum(b["profit"] for b in decided)
    roi = f"{profit / staked * 100:+.0f}%" if staked else "n/a"
    clv = [b["net_clv_pct"] for b in group if b.get("net_clv_pct") is not None]
    clv_s = f"{sum(clv) / len(clv):+.1f}% (n={len(clv)})" if clv else "n/a"
    flag = " ⚠️small" if len(group) < MIN_N else ""
    return f"{label}: {w}-{len(decided) - w} · ROI {roi} · CLV {clv_s}{flag}"


def build(bet_ledger: dict, dimension: str = "all") -> str:
    settled = [b for b in bet_ledger.values() if b["status"] in ("won", "lost", "void")]
    if dimension != "all" and dimension not in DIMENSIONS:
        return f"Unknown breakdown '{dimension}'. Try: /breakdown [{' | '.join(DIMENSIONS)}]"
    if not settled:
        return "No settled bets yet - nothing to break down."

    dims = DIMENSIONS if dimension == "all" else {dimension: DIMENSIONS[dimension]}
    lines = [f"🔍 Breakdown - {len(settled)} settled bets", "(net CLV is the signal; ROI is noisy until n is large)"]
    for title, fn in dims.values():
        groups = {}
        for b in settled:
            groups.setdefault(fn(b), []).append(b)
        lines.append(f"\n{title}")
        for label, group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            lines.append(_row(label, group))
    return "\n".join(lines)
