---
name: trader-scanner
description: >-
  Chart Scanner. Scans thousands of charts for setups: opening-range
  breakouts, flags, oversold bounces. Builds the list of Indian equities from
  NSE/BSE symbol directories, runs a pre-market scan of daily closes
  (20-day closing-high breakout, bull flag, reclaimed the 20-day average,
  oversold, oversold bounce) and an intraday opening-range breakout scan on
  5-minute bars, then writes trader/watchlist.json for trader-news and
  trader-entry. Uses free Yahoo Finance data, bar by bar. Use when the user
  says "scan the market", "find me setups", "what is breaking out",
  "opening range breakouts", "scan for bull flags", "oversold stocks",
  "pre-market scan", "build my watchlist", "what should I look at today",
  or at the start of a trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads thousands of free charts and lists the ones that match a rule. That is all it does. A scan is a list of charts that match a rule, not a list of stocks to buy, and a setup on a chart is not a prediction. Most people who day trade lose money; the scanner does not change that. It only saves you from flipping through thousands of charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                       # -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                          # before the open -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,INFY  # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                            # after 9:50 AM IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:15                 # cut the clock at 10:15 AM IST
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Flags: `--min-price 50` and `--min-volume` (daily 1,000,000, orb 0),
`--or-minutes 15`, `--max-confirm 200` (orb stage 2),
`--now "2026-10-19 10:15"` (India time) to pin the clock, `--offline PATH`
to read saved Yahoo files, `--no-write`, `--show N`, `--json`. Exit code 0
when the scan found something, 1 when it found nothing or could not run (the
reason is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news and trader-entry read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 15:30) |

## The universe

`universe` builds the Indian market list from official NSE/BSE symbol lists or a curated exchange symbol dump and keeps a row when, in this order:

1. It is not a test issue, not a depository receipt, not a mutual fund, not an ETF, and not a small-case / weird instrument.
2. It is a plain ticker: 1 to 10 letters, optionally with a market suffix like `.NS`, `.BO`, or `.NSE`/`.BSE` when the source uses it.
3. It is not a right, warrant, bond, debenture, preference share, or other non-common instrument.
4. In: it is a common share, ordinary share, equity share, or a plain listed stock on NSE/BSE.
5. Out: the name still says unit, right, bond, preferred, preference, warrant, or debt instrument.
6. In: everything else that looks like a normal listed equity share (for example `RELIANCE`, `TCS`, `INFY`, `ICICIBANK`, `HDFCBANK`).

The rule keeps broad Indian equities and excludes instruments that are not ordinary stock names. The market universe is then filtered by liquidity and chart availability before a scan runs.

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so a broad list of Indian equities takes many calls. Liquidity comes from the spark meta: last price at least `--min-price` and last session's volume at least `--min-volume`. Run it before the open or after the close: during the session the volume is the day's so far, and today's daily bar is left out until the session closes.

The setups are computed from daily closes only, so they are close cousins of the reel's `refs/scan.py`, which used highs and lows:

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

A closing-high breakout fires more often than an intraday-high one. Hits are listed most traded first (price times volume).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 9:15, 9:20, 9:25, 9:30 and 9:35 five-minute bars. A hit is the first completed 5-minute bar to CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a request. A chart goes on only if a completed bar after the range closed at or above the highest close of the range. That is a necessary condition, so no breakout is lost.
2. Stage 2, each candidate: the v8 chart with real highs and lows, one request each. Range high = the highest high of the range bars, range low = the lowest low. On a strong morning most charts are candidates, so stage 2 checks at most `--max-confirm` (200) of them, the most traded first (price times volume so far), and prints PARTIAL with the count it skipped. `--max-confirm 0` checks them all.

Timing, live on a strong Indian morning: 100 liquid names around 10:00 AM IST takes a short time, and a broad scan of the watchlist or universe is still best done with a cut-off around 10:15 AM IST. For a fast answer, scan the daily watchlist or a list of names you trade (`--watchlist`, `--symbols`).

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is there; a missing bar means a halt or a thin stock. Null closes are dropped, a bar off the 5-minute grid (the live tick) is dropped, and a bar counts only once it is complete (start + 5 minutes). Before 9:15 AM, on a weekend or holiday, after the close, or after `no_entries_after` (an expired setup) it prints one plain line and writes nothing. Indian early closes and exchange holidays are in the calendar.

## Data and limits

- Yahoo's chart and spark endpoints are free, unofficial and can lag. Bars are 5-minute bars, bar by bar, never tick by tick. query2 first, query1 on a 429 or 5xx, one retry after a 5-second wait on a 429.
- Partial results are said as partial: "Fetched 4,980 of 5,259 charts (279 failed or had no data)". Never round a partial scan up to "the whole market".
- NSE and BSE holidays and early closes for 2026 and 2027 are respected in the calendar logic.

## Steps

1. Once a week or so: `scan.py universe`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched, liquid, scanned, hits) and the top few by setup.
3. After 9:50 AM IST (10:15 is the classic): `scan.py orb`. Tell the user how many usable charts broke their range and when, and that a later hit is closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news TICKER` (what is moving it), then `/trader-entry TICKER` (the entry bar by bar). Never pick for them.

## Example: an Indian pre-open and ORB scan

A typical scan on an Indian morning:

```
python3 scan.py orb --offline wall5m-2026-10-19.json.gz --now "2026-10-19 10:15" --min-price 0
Fetched 233 of 234 charts (1 failed or had no data); 231 usable; 95 candidates, 95 confirmed with real highs and lows.
42 of 231 charts closed above their opening-range high by 10:15 AM IST:
   9:50 AM  RELIANCE   ₹2,978  range ₹2,950 to ₹2,965  +0.55% over
  ...
  10:15 AM TCS       ₹3,860  range ₹3,780 to ₹3,835  +0.65% over
```

The user picks a chart and Claude hands it to `/trader-news TCS`, then `/trader-entry TCS`.

The pre-market scan tags names like RELIANCE, TCS, INFY, ICICIBANK and HDFCBANK as breakout candidates when their daily closes clear the 20-day range; oversold or flag setups are also surfaced in the same way.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy, never calls data real time, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the order tool is set to "Needs approval" (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
