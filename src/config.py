import os

# Secrets / credentials (set as env vars or GitHub Actions secrets)
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Scan settings
REGION = os.environ.get("ODDS_REGION", "au")
MARKET = os.environ.get("ODDS_MARKET", "h2h")  # moneyline; spreads/totals are mostly US-only on this API

EV_THRESHOLD = float(os.environ.get("EV_THRESHOLD", "0.03"))   # 3% minimum edge to alert
MIN_BOOKS = int(os.environ.get("MIN_BOOKS", "3"))              # min bookmakers needed for retail-consensus fallback
MIN_EV_DELTA_TO_REALERT = float(os.environ.get("MIN_EV_DELTA_TO_REALERT", "1.0"))  # percentage points

# Only spend a credit on a sport's /odds endpoint if it has something
# starting within this many hours. Checking *whether* something's coming up
# uses the free /events endpoint, so this is what keeps credit usage low
# between game days instead of burning quota on sports with nothing on.
SCAN_WINDOW_HOURS = float(os.environ.get("SCAN_WINDOW_HOURS", "3"))

# Betfair Exchange AU - preferred fair-value anchor. Real two-sided market
# price rather than a single retail book's opinion, and it's already
# included in the au region pull at no extra API cost.
BETFAIR_KEY = os.environ.get("BETFAIR_KEY", "betfair_ex_au")

FIXED_SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "aussierules_afl",
    "rugbyleague_nrl",
]

STATE_FILE = os.environ.get("STATE_FILE", "data/state.json")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
