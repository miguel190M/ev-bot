import os

# Secrets / credentials (set as env vars or GitHub Actions secrets)
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Scan settings
REGION = os.environ.get("ODDS_REGION", "au")  # default region for most sports
DEFAULT_MARKET = os.environ.get("ODDS_MARKET", "h2h")  # default market for most sports

# Per-sport market overrides (default is h2h only).
SPORT_MARKET_OVERRIDES = {
    # Soccer 'totals' (over/under) used to be pulled here, but across 89 alerts
    # it never produced a single one while doubling each league's cost per
    # pull (4 credits -> 2), so every sport is h2h-only now. Add a
    # "sport_key": "h2h,totals" entry to bring it back for one league.
}


def get_markets_for_sport(sport_key: str) -> str:
    return SPORT_MARKET_OVERRIDES.get(sport_key, DEFAULT_MARKET)

# Extra regions per sport on top of the default (cost = markets x regions credits per pull).
SPORT_REGION_OVERRIDES = {
    # NFL/MLB/NHL dropped their 'us' region: Pinnacle is the reference now, so
    # the extra US books only cost a credit per pull (3 -> 2). NBA keeps it.
    "basketball_nba": "au,us",
}


# Sharp reference: Pinnacle (key "pinnacle") lives in The Odds API's "eu"
# region, which costs +1 credit per market on top of whatever regions are
# already pulled. Pinnacle runs a very low margin and moves on sharp money,
# so its de-vigged line is a far better fair-value estimate than the median
# of soft AU/US books (whose margins and favourite-longshot bias were
# producing phantom edges on long shots). When Pinnacle quotes an outcome
# its line is the fair price; otherwise the retail-consensus fallback is
# used. Set USE_SHARP_REFERENCE=0 to stop pulling the eu region (saves
# credits) and go back to consensus-only.
USE_SHARP_REFERENCE = os.environ.get("USE_SHARP_REFERENCE", "1").strip() not in ("0", "false", "False", "")
SHARP_REGION = "eu"
SHARP_REFERENCE_BOOKS = [b.strip() for b in os.environ.get("SHARP_REFERENCE_BOOKS", "pinnacle").split(",") if b.strip()]

# Cross-check: when the sharp book AND the soft-book median (>= MIN_BOOKS
# books) both price an outcome, and their fair probabilities differ by more
# than this many percent (relative), the two disagree - one is probably stale,
# or something real is going on. The bet is still evaluated, but against the
# LOWER of the two probabilities (the edge has to survive both), and the alert
# is flagged low-confidence with both numbers shown.
SHARP_DISAGREE_PCT = float(os.environ.get("SHARP_DISAGREE_PCT", "15"))

# Exchanges returned by the eu region. Their back prices carry no bookmaker
# margin (and betfair_ex_eu is the same exchange you bet on), so they must
# never feed the reference consensus.
REFERENCE_EXCLUDE_BOOKS = {"betfair_ex_eu", "betfair_ex_uk", "matchbook"}


def get_regions_for_sport(sport_key: str) -> str:
    regions = SPORT_REGION_OVERRIDES.get(sport_key, REGION)
    if USE_SHARP_REFERENCE and SHARP_REGION not in regions.split(","):
        regions = f"{regions},{SHARP_REGION}"
    return regions

# The minimum edge required to alert SCALES with the bettable book's price
# rather than being one flat number. Rationale: the reference consensus is
# a probability estimate with real uncertainty in it, and that uncertainty
# doesn't translate evenly into odds - a small error in estimated
# probability barely shifts the implied odds for a favorite, but the same
# error swings the implied odds much further at longer prices (since
# odds = 1/probability is a curve, not a straight line). A flat threshold
# is therefore easier to clear by estimation noise alone, not real edge,
# the longer the price gets. Linear fit: threshold = SLOPE * price +
# INTERCEPT. Defaults reproduce ~3% at odds of 2.0 (matching the old flat
# default at a "typical" price), ~5% at odds of 3, ~7% at odds of 4.
EV_THRESHOLD_SLOPE = float(os.environ.get("EV_THRESHOLD_SLOPE", "0.02"))
EV_THRESHOLD_INTERCEPT = float(os.environ.get("EV_THRESHOLD_INTERCEPT", "-0.01"))


def get_ev_threshold(price: float) -> float:
    return EV_THRESHOLD_SLOPE * price + EV_THRESHOLD_INTERCEPT

# Upper sanity cap on edge. Real, bettable edges against a multi-book
# consensus are almost never this large - anything above it is far more
# likely a stale price, a suspended market still showing old odds, or a
# data error than genuine value, so it's suppressed rather than alerted.
MAX_EV_PCT = float(os.environ.get("MAX_EV_PCT", "20"))

# Closing-line capture for CLV: an open bet whose event starts within this
# many minutes gets a dedicated odds pull (if its sport wasn't already
# fetched this run) so a pre-kickoff fair price is always recorded. Must be
# comfortably longer than the 30-min cron interval, since GitHub Actions
# schedules can run 5-20 min late. Also runs inside the sleep window, but
# only when an open bet actually needs it.
CLV_CAPTURE_MINUTES = float(os.environ.get("CLV_CAPTURE_MINUTES", "45"))
MIN_BOOKS = int(os.environ.get("MIN_BOOKS", "3"))              # min bookmakers needed for retail-consensus fallback
MIN_EV_DELTA_TO_REALERT = float(os.environ.get("MIN_EV_DELTA_TO_REALERT", "1.0"))  # percentage points

# Only spend a credit on a sport's /odds endpoint if it has something
# starting within this many hours. Checking *whether* something's coming up
# uses the free /events endpoint, so this is what keeps credit usage low
# between game days instead of burning quota on sports with nothing on.
# This is the DENSE "near" window - checked every run, unchanged. See
# FAR_WINDOW_HOURS below for the sparser outer tier.
SCAN_WINDOW_HOURS = float(os.environ.get("SCAN_WINDOW_HOURS", "3"))

# Widens effective coverage without linearly multiplying credit cost: a
# sport with something between SCAN_WINDOW_HOURS and FAR_WINDOW_HOURS away
# only gets checked once every FAR_CHECK_INTERVAL_HOURS, not every run.
# Naively widening SCAN_WINDOW_HOURS to cover the same range would check
# every run for the whole span (4x the cost here); this tiered approach
# gets the same 12h of coverage for roughly 1.5x the cost of the 3h-only
# version, since the far zone only needs occasional checks to catch a
# mispriced line, not constant polling. See scheduling.scan_tier() and
# data/far_scan_state.json (tracks last far-zone check per sport).
FAR_WINDOW_HOURS = float(os.environ.get("FAR_WINDOW_HOURS", "12"))
FAR_CHECK_INTERVAL_HOURS = float(os.environ.get("FAR_CHECK_INTERVAL_HOURS", "4"))

# Where the alerts actually come from: boxing, MMA, cricket and tennis produce
# most alerts (boxing mostly 3-12h before the fight, i.e. the far zone), so
# those sports get a wider far window and much more frequent far checks.
NICHE_PREFIXES = ("boxing_", "mma_", "cricket_", "tennis_")
NICHE_FAR_WINDOW_HOURS = float(os.environ.get("NICHE_FAR_WINDOW_HOURS", "24"))
NICHE_FAR_INTERVAL_HOURS = float(os.environ.get("NICHE_FAR_INTERVAL_HOURS", "1"))

# Big, efficient markets rarely show edges and they vanish within minutes, so
# these sports are only re-pulled in the near zone every this-many minutes
# instead of every run. NBA is deliberately NOT here (full 30-minute cadence).
# A sport is never throttled while you hold an open bet on it that starts
# within SCAN_WINDOW_HOURS, so the closing line (CLV) is still captured.
THROTTLED_SPORTS = {
    "americanfootball_nfl", "baseball_mlb", "icehockey_nhl", "soccer_epl",
    "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_germany_bundesliga",
    "soccer_uefa_champs_league", "soccer_usa_mls",
}
THROTTLED_NEAR_INTERVAL_MINUTES = float(os.environ.get("THROTTLED_NEAR_INTERVAL_MINUTES", "120"))

# Runs fire a few seconds apart from exactly 30/60/... minutes, so an interval
# check is allowed to be this many minutes early rather than slipping a whole run.
INTERVAL_SLACK_MINUTES = 5


def _is_niche(sport_key: str) -> bool:
    return sport_key.startswith(NICHE_PREFIXES)


def get_far_window_hours(sport_key: str) -> float:
    return max(FAR_WINDOW_HOURS, NICHE_FAR_WINDOW_HOURS) if _is_niche(sport_key) else FAR_WINDOW_HOURS


def get_far_interval_hours(sport_key: str) -> float:
    return min(FAR_CHECK_INTERVAL_HOURS, NICHE_FAR_INTERVAL_HOURS) if _is_niche(sport_key) else FAR_CHECK_INTERVAL_HOURS


def get_near_interval_minutes(sport_key: str) -> float:
    """0 = pull on every run."""
    return THROTTLED_NEAR_INTERVAL_MINUTES if sport_key in THROTTLED_SPORTS else 0.0

# Skip the run entirely (no credits spent, no Telegram polling) while inside
# this Sydney-local-time window - e.g. while you're asleep. Automatically
# tracks the AEST/AEDT daylight-saving switch since it's computed from the
# Australia/Sydney timezone each run, not a fixed UTC offset.
SLEEP_START_HOUR = int(os.environ.get("SLEEP_START_HOUR", "1"))   # inclusive
SLEEP_END_HOUR = int(os.environ.get("SLEEP_END_HOUR", "7"))       # exclusive

# Daily digest (see src/daily_digest.py): sent by the first run on or after
# this Sydney hour. Keep it outside the sleep window. The slate covers
# events starting in the next DAILY_SLATE_HOURS; only the top
# DAILY_SLATE_MAX by edge are listed (Telegram caps messages at 4096 chars).
DAILY_DIGEST_HOUR = int(os.environ.get("DAILY_DIGEST_HOUR", "9"))
DAILY_SLATE_HOURS = float(os.environ.get("DAILY_SLATE_HOURS", "24"))
DAILY_SLATE_MAX = int(os.environ.get("DAILY_SLATE_MAX", "8"))

# Bookmakers you can actually place bets through. Every other bookmaker
# returned by the API is used purely to build the fair-value consensus
# these get checked against - and is excluded from that consensus itself,
# so a book's own price is never compared to a "fair line" that already
# includes it. Already included in the region pulls at no extra API cost.
BETTABLE_BOOKS = [b.strip() for b in os.environ.get("BETTABLE_BOOKS", "betfair_ex_au,sportsbet").split(",")]

# Betfair Exchange charges commission on NET WINNINGS only (never on a
# loss, and never on Sportsbet - its margin is already baked into the
# quoted price with no extra fee stacked on top). These are current 2026
# Betfair AU Market Base Rates. NRL specifically carries a much higher rate
# than every other sport here, so it needs its own entry rather than one
# flat default - a bet that looks like a solid edge before commission can
# be barely breakeven after it once NRL's 10% is applied.
COMMISSION_BOOKS = {"betfair_ex_au"}
SPORT_COMMISSION_RATES = {
    "rugbyleague_nrl": 0.10,
}
DEFAULT_COMMISSION_RATE = float(os.environ.get("BETFAIR_COMMISSION_DEFAULT", "0.06"))


def get_commission_rate(book_key: str, sport_key: str) -> float:
    """0.0 for any book that doesn't charge commission at all (e.g. Sportsbet)."""
    if book_key not in COMMISSION_BOOKS:
        return 0.0
    return SPORT_COMMISSION_RATES.get(sport_key, DEFAULT_COMMISSION_RATE)

FIXED_SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "aussierules_afl",
    "rugbyleague_nrl",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "icehockey_nhl",
    "soccer_uefa_champs_league",
    "soccer_germany_bundesliga",
    "soccer_australia_aleague",
    "mma_mixed_martial_arts",
    "boxing_boxing",
    "cricket_big_bash",   # Big Bash League (Dec-Jan); other cricket comps are auto-discovered
    "americanfootball_ncaaf",   # trial: college sports, thin/soft lines, many games per pull
    "basketball_ncaab",
    "soccer_usa_mls",
]

# Sport groups (as listed by The Odds API /sports) whose in-season competitions
# are discovered each run instead of hard-coded: tennis (one key per
# tournament) and cricket (one key per competition: tests, ODIs, T20s, BBL...).
DISCOVERED_GROUPS = ("Tennis", "Cricket")

# Sports whose results can't be read automatically from the Odds API scores
# endpoint (no scores for combat sports; cricket scores are "250/6", not a
# plain number). Bets on these stay "open" until settled by hand, and the bot
# must not keep paying 2 credits per run to re-fetch scores that can't resolve.
NO_AUTO_SCORE_PREFIXES = ("mma_", "boxing_", "cricket_")

# How long after kickoff a still-open bet on a no-auto-score sport is listed in
# the daily report as "awaiting settlement" (reply /settle <id> won|lost|void).
SETTLE_PROMPT_HOURS = 6
SETTLE_PROMPT_HOURS_TEST_CRICKET = 72

STATE_FILE = os.environ.get("STATE_FILE", "data/state.json")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Credit-health alerts (see src/health.py). A failed paid /odds pull is
# otherwise silent (it only prints to the Actions log), so the bot can sit
# blind for days. Telegram warns when pulls fail, repeats at most every
# HEALTH_REALERT_HOURS, and says when they recover. Low-credit warnings fire
# once as the balance first falls below each level, and re-arm after the
# balance climbs back above HEALTH_LOW_CREDIT_REARM (i.e. after a reset or
# top-up).
HEALTH_STATE_FILE = os.environ.get("HEALTH_STATE_FILE", "data/health_state.json")
HEALTH_REALERT_HOURS = float(os.environ.get("HEALTH_REALERT_HOURS", "6"))
HEALTH_LOW_CREDIT_LEVELS = [2000, 500]
HEALTH_LOW_CREDIT_REARM = 5000

# How each reference book's margin is removed before building the consensus.
# "shin" (default) and "power" take proportionally MORE margin off long shots
# than favourites, correcting the favourite-longshot bias (shin is the standard
# published method; power is the most aggressive). "multiplicative" is the old
# behaviour (scale every outcome equally), which overstated long shots' true
# probability and so flagged long-priced Betfair/Sportsbet lines as value far
# too often. Set DEVIG_METHOD=multiplicative to revert.
DEVIG_METHOD = os.environ.get("DEVIG_METHOD", "shin").strip().lower()

# Edge threshold for bets priced against the SHARP book (Pinnacle). The scaling
# threshold above (2% x price - 1%) was built for the noisy soft-book
# consensus; against Pinnacle's much tighter line it asked for e.g. +16% over
# fair at odds of 5, so almost nothing could clear. Pinnacle-anchored bets use
# a flat net-of-commission edge instead: SHARP_EV_BASE_PCT, plus an optional
# SHARP_EV_SLOPE x (price - 3) for long prices (0 = flat). The retail-consensus
# fallback keeps the scaling threshold.
SHARP_EV_BASE_PCT = float(os.environ.get("SHARP_EV_BASE_PCT", "3"))
SHARP_EV_SLOPE = float(os.environ.get("SHARP_EV_SLOPE", "0"))

# Rolling per-run scan stats used for the daily digest's "closest call" line.
SCAN_STATS_FILE = os.environ.get("SCAN_STATS_FILE", "data/scan_stats.json")


def get_edge_threshold(price: float, anchor: str) -> float:
    """Minimum EV (as a fraction) to alert, given where the fair price came from."""
    if anchor == "retail_consensus":
        return get_ev_threshold(price)
    return SHARP_EV_BASE_PCT / 100 + SHARP_EV_SLOPE * max(0.0, price - 3.0)
