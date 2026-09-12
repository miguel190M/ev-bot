import os

# Secrets / credentials (set as env vars or GitHub Actions secrets)
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Scan settings
REGION = os.environ.get("ODDS_REGION", "au")  # default region for most sports
MARKET = os.environ.get("ODDS_MARKET", "h2h")  # moneyline; spreads/totals are mostly US-only on this API

# NBA and NFL additionally pull the 'us' region on top of the default -
# US books are far deeper/sharper for these two home-turf sports, giving a
# much better fair-value consensus for Betfair's price to be checked
# against. AFL/NRL have no US market coverage anyway, and EPL isn't
# getting this treatment yet (UK/EU would be the sharper region there, not
# US, if that's wanted later). Costs roughly double the credits per call
# for these two sports specifically, since cost scales with markets x
# regions - everything else stays on the single default region.
SPORT_REGION_OVERRIDES = {
    "basketball_nba": "au,us",
    "americanfootball_nfl": "au,us",
}


def get_regions_for_sport(sport_key: str) -> str:
    return SPORT_REGION_OVERRIDES.get(sport_key, REGION)

EV_THRESHOLD = float(os.environ.get("EV_THRESHOLD", "0.03"))   # 3% minimum edge to alert
MIN_BOOKS = int(os.environ.get("MIN_BOOKS", "3"))              # min bookmakers needed for retail-consensus fallback
MIN_EV_DELTA_TO_REALERT = float(os.environ.get("MIN_EV_DELTA_TO_REALERT", "1.0"))  # percentage points

# Only spend a credit on a sport's /odds endpoint if it has something
# starting within this many hours. Checking *whether* something's coming up
# uses the free /events endpoint, so this is what keeps credit usage low
# between game days instead of burning quota on sports with nothing on.
SCAN_WINDOW_HOURS = float(os.environ.get("SCAN_WINDOW_HOURS", "3"))

# Skip the run entirely (no credits spent, no Telegram polling) while inside
# this Sydney-local-time window - e.g. while you're asleep. Automatically
# tracks the AEST/AEDT daylight-saving switch since it's computed from the
# Australia/Sydney timezone each run, not a fixed UTC offset.
SLEEP_START_HOUR = int(os.environ.get("SLEEP_START_HOUR", "1"))   # inclusive
SLEEP_END_HOUR = int(os.environ.get("SLEEP_END_HOUR", "7"))       # exclusive

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
    "aussierules_afl",
    "rugbyleague_nrl",
    "soccer_epl",
]

STATE_FILE = os.environ.get("STATE_FILE", "data/state.json")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
