---
name: trader-news
description: >-
  News Monitor. Tracks breaking news on every stock you watch and flags what
  moves it: Yahoo Finance headlines per ticker, each company's BSE/NSE notice
  disclosures (earnings, promoter actions, buybacks, board changes, major
  litigations, delisting or corporate actions) and how far each stock is from
  yesterday's close. Shows only what is new since the last check, newest
  first, in Indian Standard Time, tags each item (earnings, analyst, deal,
  legal, regulatory, macro, corporate action, halt, promoter, capex...) and
  never repeats one. Use when the user says "any news on RELIANCE",
  "why is this moving", "what's the news on my watchlist", "morning brief",
  "pre-open news", "monitor the news", "did anything break", "check the
  exchange notices", or after /trader-scanner finds setups.
argument-hint: "[tickers]"
---

# trader-news

A chart can look perfect and still be about to gap on earnings, a board change,
new promoter news, a regulatory filing, or a big corporate action. Before a
setup becomes a trade, this skill reads the feeds that carry those first, for
every stock on the watchlist, and tells you only what is new. It also prints
how far each stock has moved today, so a headline and a move sit side by side.

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                        # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE INFY --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-exchange --json
```

## What it reads and writes

| file / feed | what |
| --- | --- |
| `--tickers`, else `trader/watchlist.json` | the scanner's hits (trader-scanner) |
| `trader/plan.json` | the trade you are planning (trader-exit) |
| `trader/portfolio.json` | what you hold (trader-broker records fills there) |
| Yahoo Finance headline RSS | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=RELIANCE.NS&region=IN&lang=en-IN` |
| Yahoo Finance chart endpoint | the last price against yesterday's close (unofficial, can lag) |
| BSE/NSE exchange notice feed | corporate announcements, board meetings, buybacks, dividend, rights, litigation, delisting, promoter action, and material disclosures |
| `trader/state/news.json` | what has been shown (kept 30 days) and each ticker's company/issuer mapping |

## The rules

- **Headlines are leads, not facts.** Before telling the user something
  happened, open the story or the exchange notice and read it. Quote the source
  and link it. Never summarise a paywalled or blocked story you could not read:
  say so.
- **Exchange notices beat headlines.** If a BSE/NSE disclosure and a headline
  disagree, the exchange filing is the stronger source of truth.
- **Say what it touches.** Every item lists the tickers it touches and its
  tags: earnings, analyst, legal, deal, capital, people, risk, regulatory,
  macro, promoter, corporate action, guidance, delisting, or halt. Exchange
  notices marked `!` carry important material events: earnings or results
  (Q1/Q2/Q3/Q4), promoter action, debt or capital raise, board change,
  litigation, delisting notice, bankruptcy or insolvency notice, or a cyber or
  fraud disclosure.
- **MOVING** marks a stock 3% or more from yesterday's close (`--move-pct`).
  A move with no headline is worth saying out loud too.
- **No predictions.** Report what was published and how far the price is from
  yesterday's close. Never say what the stock will do next.

## Steps

1. Run the check: `python3 "${CLAUDE_SKILL_DIR}/news.py"`. Exit code 1 means
   nothing new. `--all` shows items already seen, `--json` gives everything
   machine readable, and `--dry-run` leaves the state alone.
2. Read the items that matter: every `!` exchange filing, anything tagged
   earnings, promoter, legal, regulatory, risk, or delisting, and every MOVING
   ticker first.
3. Write a short brief, per ticker: what happened, the source and link, the
   move, and one line on why it matters to the setup (for example "earnings are
   this week: an overnight gap can jump past any stop").
4. If a story changes the picture, say so before `/trader-entry` and
   `/trader-exit`: an earnings date inside the trade, a regulatory action,
   a buyback, a promoter stake change, or a delisting filing. Never act on a
   headline alone.

During the session: `/loop 15m /trader-news`, or a scheduled task each
morning before the open.

## Example: the reel

Monday 2026-11-16, RELIANCE is trading after a strong pre-open move. The check
at 9:45 IST (Yahoo Finance RELIANCE.NS feed, 12 headlines since 8:00) leads with
real stories: "Reliance Industries Q2 earnings due this week" (8:05, earnings),
"Reliance Jio to expand 5G services across major metro circles" (8:30, deal,
capital), and "NSE/BSE notice: promoter stake movement disclosed" (9:10,
promoter, regulatory). The brief: "Reliance has a material disclosure and an
earnings date in play; the stock can gap on a big open. No direct exchange
notice was missed." At 10:12 the price line reads `RELIANCE 2872.45 +2.70% vs
yesterday's close 2796.80 at 10:12 IST  MOVING`. When a ticker has no news, say
so rather than padding the brief.

## What it never does

- Never invents or embellishes a story, a quote or a number.
- Never trades on news, and never tells the user to buy or sell because of a
  headline.
- Never hammers a server: one request per feed per ticker, a pause between
  calls, and exchange-rate or feed limits stay far away.

## Safety

Education and tooling, not financial advice. This skill only reads and
reports. Nothing places an order except `/trader-broker`, after
`/trader-risk` passes and the user types an explicit yes for that order.
