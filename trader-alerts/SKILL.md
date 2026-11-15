---
name: trader-alerts
description: >-
  Price Alerts. Rings when a price, a stop or the opening bell hits. Turns
  the trade plan into three alerts in one go (the stop, the target and "flat
  by close" at your flat-by time), plus above / below / stop / target levels,
  percent moves from the previous close, any time of day, and the NSE/BSE
  opening bell, each ringing once so you are not spammed. Knows NSE/BSE hours
  (09:15 to 15:30 IST) with the 2026–2028 holidays and special Diwali Muhurat
  sessions, works out IST itself, fetches free delayed quotes (Yahoo chart
  JSON with automatic .NS suffixing) one ticker at a time, and writes
  trader/prices.json for sizing and the risk check. Use when the user says
  "alert me when", "tell me if RELIANCE hits", "watch my stop", "watch my
  trade", "remind me to close by 3:15", "is the market open", "when does the
  market open", "get me a price", or right after /trader-exit writes a plan.
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
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE/BSE open or closed, next open
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat by close from trader/plan.json
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 1285.50
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --target 1340.00
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:15 --label "flat by close" --before-close
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TCS --pct 3
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" check                          # exit 0 = something rang
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write         # -> trader/prices.json
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # portfolio + plan tickers
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "\${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-ns-plan-stop
```

`--now "2026-10-19 15:15"` pins the clock (IST); `--offline DIR`
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
| `time` | the IST clock passed `at` ("15:15") on a trading day | once per trading day |
| `opening_bell` | the NSE/BSE is open (09:15 IST) | once per trading day |

A rule with `"date"` is watched on that IST date only; `--from-plan`
rules carry the plan's date, so yesterday's stop never rings today. A `time`
rule with `"before_close": true` shifts dynamically if a special session closes
at a non-standard time instead of the regular 15:30 IST close.

## Quotes

- `yahoo` (default): `query2.finance.yahoo.com/v8/finance/chart/<TICKER>.NS`,
  an unofficial free JSON endpoint, one request per ticker, half a second
  apart. Bare Indian tickers automatically get `.NS` appended (or pass `.BO`
  for BSE, `^NSEI` for Nifty 50, `^BSESN` for Sensex). On a 429 it waits and
  tries once more; on a 429 or a 5xx after that it tries `query1`. It
  identifies itself as `day-trader-skill/2.0`.
- Free quotes are unofficial, delayed and can lag. They are fine for alerts
  and for checking a size, not for timing an order. The broker's price is the
  one that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If Yahoo is down, read the price from the broker connector (e.g. Zerodha
  Kite, Upstox, Dhan, or IBKR `get_price_snapshot`) and write it into
  `trader/prices.json` as `{"as_of": "...Z", "prices": {"RELIANCE.NS": 1312.40}}`.

## The NSE/BSE clock

Regular session 9:15 a.m. to 3:30 p.m. IST (`UTC+05:30`), closed on weekends
and on these holidays, from ://nseindia.com
and ://bseindia.com:

- 2026 (Official): Jan 15, Jan 26, Mar 3, Mar 26, Mar 31, Apr 3 (Good Friday),
  Apr 14, May 1, May 28, Jun 26, Sep 14, Oct 2, Oct 20, Nov 10, Nov 24, Dec 25.
  Special Diwali Muhurat session on Sunday, Nov 8.
- 2027 (Projected): Jan 26, Mar 10, Mar 22, Mar 26 (Good Friday), Apr 14,
  Apr 15, Apr 19, May 17, Jun 15, Oct 29 (Diwali Laxmi Pujan / Muhurat Trading).
- 2028 (Projected): Jan 26, Feb 23, Apr 3, Apr 7, Apr 14 (Good Friday /
  Ambedkar Jayanti), May 1, May 5, Aug 15, Aug 23, Sep 27, Oct 2, Oct 17
  (Diwali Laxmi Pujan / Muhurat Trading), Oct 18, Nov 2, Dec 25.

IST has no Daylight Saving Time (`UTC+05:30` year-round), so the tool needs no
time zone files and ignores the computer's own zone. For any other year it says
the holiday list is unknown.

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

RELIANCE.NS on Monday 2026-10-19: entry 1305.00 at 09:45 AM IST, stop 1285.50,
target 1340.00, flat by 15:15. `add --from-plan` writes `reliance-ns-plan-stop`,
`reliance-ns-plan-target` and `reliance-ns-flat-by` for that day. A `check` at
10:53 reads the delayed quote, 1312.40, between the stop and the target:


```
NSE OPEN (2026-10-19 10:53 IST, regular session).
Nothing hit. 3 rule(s) watched today, RELIANCE.NS ₹1312.40.

```

At 3:15 PM IST:

```
ALERT Flat by close: it is 15:15 IST (set for 15:15), the market closes at 15:30 IST. If RELIANCE.NS is still
open, square it off: trader-broker flatten --symbol RELIANCE.NS builds the sell ticket, then trader-risk and your yes.
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
- Broker keys live in environment variables or the Claude Desktop config, never in chat.