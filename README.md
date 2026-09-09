# ev-bot

Scans NBA, NFL, AFL, NRL and Tennis odds across Australian bookmakers
(Sportsbet, TAB, Neds, Ladbrokes and others in The Odds API's `au` region),
finds prices that beat a de-vigged multi-book consensus by a meaningful
margin, and sends you a Telegram alert.

## How it decides "+EV"

**Primary method - Betfair Exchange anchor.** Betfair Exchange AU
(`betfair_ex_au`) is included in the same `au` region pull as the retail
books, at no extra API cost. Unlike a retail bookmaker, an exchange reports
two real, opposing prices per outcome: the best price you can **back** it at
and the best price you can **lay** it at (bet against it). The midpoint
between those two - real money on both sides of the market, not one book's
opinion - is a much tighter fair-value estimate than de-vigging a single
retail book. Every retail bookmaker's price gets checked against that line.

**Fallback - retail median consensus.** Used only for events where Betfair
has no odds yet (thin liquidity on a smaller market). Each retail book is
de-vigged individually, and a book's price is judged against the *median*
de-vigged price from every *other* book (never itself). Every alert is
tagged with which method produced it, and fallback alerts carry a lower
confidence note - AU retail books share ownership groups (Sportsbet=Flutter,
TAB=Tabcorp, Ladbrokes/Neds=Entain) and often shade off each other's lines,
so a "median of retail books" isn't as independent a signal as it sounds.

**Why Betfair specifically, beyond better pricing:** exchanges make money on
commission regardless of who wins, so unlike retail bookmakers they don't
limit or close accounts of consistently winning customers. If this tool
finds a real edge, Betfair is also the venue where you can actually keep
acting on it long-term.

**Still a caveat worth keeping in mind:** this is a screening signal, not a
proven edge. Betfair AU liquidity can be thin on lower-tier NRL/AFL matchups
and some tennis, in which case you're back on the weaker fallback method -
check the `anchor` field (or the confidence note in the Telegram alert)
before trusting a flagged price.

## Setup

1. **Get an Odds API key** — sign up at https://the-odds-api.com (free tier:
   500 credits/month, no card required).
2. **Reuse or create a Telegram bot** — you already have one wired up for
   card-bot; same bot/chat works fine here, or spin up a second bot via
   @BotFather if you'd rather keep the alert streams separate.
3. **Push this repo to GitHub**, then add repo secrets (Settings → Secrets
   and variables → Actions):
   - `ODDS_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. The workflow in `.github/workflows/scan.yml` runs every 30 min by
   default and commits `data/state.json` back to the repo so it doesn't
   re-alert you on the same edge every run.

## Credit budget - how the smart scheduling works

Instead of scanning everything on a fixed clock, each run first checks the
**free** `/events` endpoint for every sport - that costs nothing. Only sports
with something starting within `SCAN_WINDOW_HOURS` (default 3) get the
**paid** `/odds` call. So on a quiet afternoon with nothing on, a run can
cost 0 credits; as game time approaches for whatever's on, it naturally
starts pulling real odds every 30 min without you having to guess the right
clock time.

Rough cost per sport, per approaching game: with a 3-hour window and 30-min
runs, a single game gets ~6 paid checks total as it approaches (once every
30 min for the 3 hours before kickoff), then drops back to free once it's
started. Compare that to old fixed-time scanning, where you paid the same
credit whether or not anything was actually happening.

Actual monthly usage depends entirely on your schedule - more concurrent
sports (e.g. NBA finals + NRL finals + a tennis Slam all at once) costs
more than a quiet week. **Watch the Actions log for the first couple of
weeks** (each run prints credits used and credits remaining) to get a feel
for your real usage before deciding if you need to upgrade off the free
500/month tier.

| Plan | Credits/mo | Rough guide |
|---|---|---|
| Free | 500 | Fine for 1-2 sports in season at a time with the smart scan |
| Starter (~$25 AUD/mo) | 20,000 | Comfortable even with several overlapping sports |

If you'd rather scan less densely near kickoff to stretch the free tier
further, lower `SCAN_WINDOW_HOURS` (fewer paid checks per game) or change
the cron interval in `.github/workflows/scan.yml` from `*/30` to something
like `*/60`.

## Tuning

Set these as env vars (or edit the workflow's `env:` block):

- `EV_THRESHOLD` (default `0.03`) — minimum edge to alert on. Lower = more
  alerts, more noise from consensus imprecision.
- `MIN_BOOKS` (default `3`) — minimum number of books quoting an event
  before it's considered for EV at all (fallback method only). Higher = more
  trustworthy consensus, fewer events qualify.
- `SCAN_WINDOW_HOURS` (default `3`) — how far ahead of kickoff to start
  spending credits on a sport. Lower = fewer credits used, less lead time to
  catch a moving line before the game starts.

## Local testing

`python test_local.py` runs the EV math (both Betfair-anchor and fallback
paths) against synthetic data. `python test_scheduling.py` checks the
credit-saving scheduling logic. Neither needs an API key or network -
useful for checking any changes before they touch your real credit quota.

## Files
