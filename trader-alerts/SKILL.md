---
name: trader-alerts
description: >-
  Price Alerts. Rings when a price, a stop or the opening bell hits. Turns
  the trade plan into three alerts in one go (the stop, the target and "flat
  by close" at your flat-by time), plus above / below / stop / target levels,
  percent moves from the previous close, any time of day, and the NSE/BSE
  opening bell, each ringing once so you are not spammed. Knows Indian market
  hours with Indian holidays and special Muhurat sessions, works out IST
  itself, fetches free delayed quotes (Yahoo chart JSON, Stooq CSV) one ticker
  at a time, and writes trader/prices.json for sizing and the risk check. Use
  when the user says "alert me when", "tell me if RELIANCE hits", "watch my
  stop", "watch my trade", "remind me to close by 15:30", "is the market
  open", "when does the market open", "get me a price", or right after
  /trader-exit writes a plan.
argument-hint: "[ticker] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a bracket order the stop-loss and the
take-profit already sit at the broker and do the work; the alerts tell the
user what happened and when it is time to be flat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE/BSE open or closed, next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat by close from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 2812.25
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --target 2890.00
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:30 --label "flat by close" --before-close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol HDFCBANK --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # exit 0 = something rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write       # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # portfolio + plan tickers
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-plan-stop
```

`--now "2026-10-19 15:30"` pins the clock (India time); `--offline DIR`
reads saved quote files instead of the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | the tickers held, for `quote --holdings` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the India clock passed `at` ("15:30") on a trading day | once per trading day |
| `opening_bell` | the NSE/BSE is open | once per trading day |

A rule with `"date"` is watched on that India date only; `--from-plan`
rules carry the plan's date, so yesterday's stop never rings today. A `time`
rule with `"before_close": true` moves 3 hours earlier on a special early-close
session if one is listed, so "flat by close" at 15:30 rings earlier when the
exchange closes early.

## Quotes

- `yahoo` (default): `query2.finance.yahoo.com/v8/finance/chart/<TICKER>`, an
  unofficial free JSON endpoint, one request per ticker, half a second apart.
  On a 429 it waits and tries once more; on a 429 or a 5xx after that it
  tries `query1`. It identifies itself as `day-trader-skill/2.0`.
- `stooq`: `stooq.com/q/l/?s=rel.ns&f=sd2t2ohlcv&h&e=csv`, Stooq's free CSV.
  It can be unavailable or delayed; the parser remains for when it is back.
- Free quotes are unofficial, delayed and can lag. They are fine for alerts
  and for checking a size, not for timing an order. The broker's price is the
  one that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If both are down, read the price from the broker connector and write it into
  `trader/prices.json` as `{"as_of": "...Z", "prices": {"RELIANCE": 2868.75}}`.

## The Indian market clock

Regular session 9:15 a.m. to 3:30 p.m. IST, closed on weekends and on these
Indian holidays, from NSE/BSE market calendars (read 2026-10-13):

- 2026: Jan 1, Jan 26 (Republic Day), Mar 3 (Mahashivratri), Apr 3 (Good Friday), Apr 14/15 (Baisakhi/Dr. Ambedkar Jayanti depending on the year), May 1, Jun 19, Aug 15, Aug 27 (Ganesh Chaturthi), Oct 20 (Dussehra), Nov 12 (Diwali Laxmi Pujan, when announced), Dec 25. Special Muhurat trading sessions are supported where applicable.
- 2027: Jan 1, Jan 26, Feb 12/13 (depending on the calendar), Mar 26 (Good Friday), Apr 6/7 (regional holiday variations), May 1, Jun 19, Aug 15, Sep 1 (Ganesh Chaturthi), Oct 30 (Dussehra), Nov 7 (Diwali), Dec 25.

The tool treats Indian Standard Time as fixed UTC+5:30 and does not depend on the
computer's own time zone. For any other year it says the holiday list is unknown.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a Claude
   scheduled task or `/loop`. Each run fetches only the tickers in today's
   rules and rings each alert once. A check reads the latest delayed quote;
   it is not a live feed, and a price can pass a level between two checks.
3. Tell the user what rang in one line each. A stop or target alert means the
   bracket order has probably filled: check `get_open_position` and record the
   fill with trader-broker. "Flat by close" means close anything still open:
   trader-broker `flatten`, then trader-risk, then the user's yes. Never act
   for them.

## Example: the reel

RELIANCE on Monday 2026-10-19: entry 2868.75 at 10:15 AM, stop 2812.25, target
2925.00, flat by 15:30. `add --from-plan` writes `reliance-plan-stop`,
`reliance-plan-target` and `reliance-flat-by` for that day. A `check` at 10:53 reads
the real 10:52 quote, 2878.50, between the stop and the target:

```
NSE/BSE OPEN (2026-10-19 10:53 India time, regular session).
Nothing hit. 3 rule(s) watched today, RELIANCE ₹2878.50.
```

At 15:30:

```
ALERT Flat by close: it is 15:30 India time (set for 15:30), the market closes at 15:30. If RELIANCE is still
open, close it: trader-broker flatten --symbol RELIANCE builds the sell ticket, then trader-risk and your yes.
```

It rings once. The next morning the plan's three alerts are no longer
watched; with `add --opening-bell`, the bell rings at 9:15.

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a quote as live. Free quotes are delayed and unofficial.
- Confirm every new rule back to the user: ticker, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a quote is
live, and never predicts where a price is going.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
