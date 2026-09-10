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

# Betfair Exchange AU - the only bookmaker whose price actually gets
# evaluated and alerted on now (retail books are used purely to build the
# fair-value consensus Betfair's price is checked against). Already
# included in the au region pull at no extra API cost.
BETFAIR_KEY = os.environ.get("BETFAIR_KEY", "betfair_ex_au")

FIXED_SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "aussierules_afl",
    "rugbyleague_nrl",
    "soccer_epl",
]

STATE_FILE = os.environ.get("STATE_FILE", "data/state.json")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
