---
name: trader-broker
description: >-
  Order Executor for the Indian market. Sends approved orders to your broker,
  paper trading by default, never without your yes. Shows each order as a
  plain ticket, including the stop-loss, take-profit and the max loss at the
  stop for bracket-style positions, plus the exact JSON for the broker order
  tool, records your yes word for word, then Claude's own Allow once / Deny
  card asks again. Builds the sell ticket that closes a day trade by your
  flat-by time, records fills, and logs each trade's max loss so trader-risk
  can enforce the daily limit. Covers broker setup, paper trading, approval
  controls, and the Indian-market flow for NSE/BSE orders. Use when the user
  says "place the order", "buy it", "execute", "send it to my broker",
  "close my position", "flatten", "get me out", "connect my broker",
  "set up paper trading", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches the market only after three
separate gates, every time, for every order:

1. trader-risk passed this exact order today (matched by fingerprint).
2. The user typed an explicit yes for this one order in the chat.
3. The user clicked Allow once on Claude's own permission card, which appears
   because the order tool is set to Needs approval.

Two yeses from the user, one PASS from the rules. No yes, no order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ID --filled-qty 8 --filled-price 1728.50
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol RELIANCE --side sell --qty 8 --price 1750.00
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE --qty 8
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the flatten ticket, and keeps the log in
`trader/state/broker.json`. `--now "2026-10-19 10:15"` pins the clock in
Indian Standard Time (IST), not US Eastern time.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time for `flatten` |

## Setup A: broker connector / order tool

This repo stays broker-agnostic, but the execution pattern is the same as in the
US version: use the user's broker tool or MCP connector, and keep order tools on
Needs approval. The broker may be Zerodha, Angel One, Upstox, or any other Indian
broker connector that exposes order tools through Claude Desktop / Claude Code.

1. The user creates a broker account with trading access and uses a paper-trading
   or demo account if available.
2. In Claude Desktop: Settings > Developer > Edit Config. That opens
   `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\`). Add the broker's
   connector or MCP config, keeping API keys or session secrets only in that local
   config file and never in the chat.
3. Restart Claude Desktop.
4. Set tool permissions. For each order tool that can place, amend, cancel or
   close a trade, pick Needs approval. Never set a buy or sell tool to Always allow.
5. Read-only tools such as account info, positions, quote snapshots and order lists
   can remain Always allow if the user wants that convenience.

In Claude Code instead of Claude Desktop, keep the order tool on ask in
`.claude/settings.json`: `"permissions": {"ask": ["mcp__broker__place_stock_order"]}`,
and never put an order tool in `allow`.

**Bracket orders in the Indian market.** If the broker supports bracket-style
orders, the tool may accept a stop-loss and a take-profit value. When those are
present, the order is effectively a protected entry with a stop-loss and target.
The ticket shows the exact stop and target and the max loss at the stop. The
broker may implement them as linked orders, but the workflow is the same: the
entry is approved first, then the protective orders follow. Keep the trade flat
by the close if the user has an intraday plan.

## Setup B: broker-specific notes

For Indian brokers, the final yes still happens in the broker UI or connector flow,
not in the chat. If the user has a broker connector that drafts orders and asks
for confirmation in that app, set `"broker": "ibkr"`-style semantics only if the
connector explicitly behaves that way, otherwise treat the broker as a standard
approval gate. This repo is designed to be generic and market-correct for
NSE/BSE, not tied to one vendor.

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order per
   question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this order
   (for example "sure", "yes to all", or a yes that names a different stock or
   amount). Ask again. Never turn a reply into a yes yourself.
4. Only after "Recorded your yes", call the place order tool with exactly the
   JSON the ticket printed. Claude's card appears: Allow once or Deny.
5. Record what happened: `ticket.py result --index N --status placed
   --broker-id <id> --filled-qty Q --filled-price P` (the fill from the response or
   broker position data), or `--status denied`, or `--status failed` with `--note`.
   A failed order is not retried without a new check and a new yes. The log keeps
   the entry's max loss for trader-risk's daily limit.

## Steps: while it is open, and out by the close

- trader-alerts watches the stop, the target and the flat-by time
  (`alerts.py add --from-plan`).
- When the stop-loss or the take-profit fills, record it:
  `ticket.py fill --symbol RELIANCE --side sell --qty 8 --price 1740.00`.
- By `flat_by` (for Indian sessions, usually before the close and often around the
  last 15 minutes, depending on the plan), anything still open gets closed:
  1. Ask the broker for the number of shares held: position or order status tool.
  2. `ticket.py flatten --symbol RELIANCE --qty 8` writes a market sell for those
     shares to `trader/orders.json`.
  3. `/trader-risk`. A sell that only closes what the user holds is never blocked
     by the daily limits or the entry window.
  4. `ticket.py show`, then the user's yes for that one order, as above.
  5. If the broker shows linked stop-loss and take-profit orders still active,
     cancel those protective legs before sending the closing order if required by
     the broker flow.

## Example: the reel

```
ORDER 1 of 1, PAPER account, broker connector
  BUY 8 RELIANCE, market, good for today
  stop-loss 1720.00
  take-profit 1765.00
  max loss about ₹1,120.00 if the stop fills at 1720.00 (it can fill worse in a fast market)
  why: breakout continuation on RELIANCE: 8 shares, bound by your ₹1,500 max loss per trade
  READY: trader-risk PASS, waiting for your yes
  Claude will call the broker order tool with exactly:
    {"symbol": "RELIANCE", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
     "order_class": "bracket", "take_profit_limit_price": "1765.00", "stop_loss_stop_price": "1720.00"}
```

The user replies "yes". Claude records it, calls the broker tool, and the card
reads "Claude wants to use the order tool" with that JSON and two buttons:
Allow once, Deny. Allow once sends it to the broker account. The `why` and the
plan stay in the file; they are never sent.

## What it never does

- Never places an order without all three gates, and never two orders on one yes.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats API keys or passwords.
- Never switches a trading account to live without the user explicitly deciding to do so.
- Never calls risky or destructive tools such as close all positions, cancel all orders,
  option or F&O mass actions, or other broad-risk commands on its own.
- Never promises a fill price: a market order and a stop fill at whatever the market gives.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision,
  in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold:
  trader-risk passed that exact order today, the user typed an explicit yes for that one order
  in the chat, and the user clicked Allow once on Claude's own card because the order tool is
  set to Needs approval. Never set an order tool to Always allow.
- No options, leverage or unauthorized margin positions unless the config allows it and the user
  confirms.
- Broker keys live in environment variables or the broker connector config, never in the chat.
