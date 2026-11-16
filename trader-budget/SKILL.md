---
name: trader-budget
description: >-
  Budget Manager for the Indian market. Sizes every position to your budget and
  your max loss per trade. Reads the trade plan from trader-exit (entry, stop,
  target), finds the whole shares that fit inside four limits (max loss per trade,
  position cap, max order, cash after your buffer), says which limit decided it,
  and writes ONE bracket order (entry, stop-loss, take-profit) to
  trader/orders.json in the exact shape of the broker order tool. A stop too far
  away for your max loss is a plain refusal, not a smaller order. Nothing is
  placed. Use when the user says "how many shares", "size this trade", "how much
  should I buy", "I have ₹5,00,000", "I only want to risk ₹10,000 a trade", "set
  my rules", "keep 10% in cash", or after /trader-exit writes a plan.
argument-hint: "[budget in rupees]"
---

# trader-budget

The Budget Manager turns a plan ("buy RELIANCE at 2,500, stop 2,440") into an
exact order ("buy 8 shares"), inside rules the user sets once. The stop decides
the size: the further away the stop, the fewer shares. It writes a proposal only.
trader-risk checks it and trader-broker asks the user yes or no. Day trading loses
most people money. Sizing to a max loss keeps each loss small; it does not make a
trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit --write        # a limit order at the plan's entry
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 2485.00 --json  # a limit order at 2485.00
```

`--now "2026-10-19 10:15"` pins the clock in Indian Standard Time (IST). A plan
for another day is refused: make a new one with trader-exit.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the rules (start from `config.example.json` in this folder) |
| `trader/plan.json` | the trade: entry, stop, target, setup, flat-by time (trader-exit writes it) |
| `trader/prices.json` | optional: a fresh price above the plan's entry means a bigger risk |
| `trader/portfolio.json` | optional: its cash caps the size |
| `trader/orders.json` | the one proposed bracket order it writes with `--write` |

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` into
`trader/config.json` and ask the user for each value in plain words:

- **budget**: how much money this is for. Only money they can afford to lose.
- **cash_buffer_pct**: how much always stays in cash (default 10).
- **max_loss_per_trade_inr**: the most one trade may lose if the stop fills at the stop (default ₹10,000).
- **max_position_pct**, **max_order_inr**, **min_order_inr**: the biggest position (75% of the
  budget), the biggest order (₹2,00,000) and the smallest order (₹500).
- The day limits trader-risk enforces: **max_daily_loss_inr** (₹40,000), **max_trades_per_day** (3),
  **min_reward_risk** (1.0), **require_stop** (true), **no_entries_before** / **no_entries_after**
  ("09:15" / "15:00") and **flat_by** ("15:30"), all IST.
- **blocked**: tickers they never want to trade.
- Keep **paper** true until they have watched it work on a paper or demo account.

## Step 2: size the trade

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" --write
```

Whole shares only: the broker takes no fractions in a bracket order. The size is the
smallest of four limits:

| limit | shares |
| --- | --- |
| max loss | `max_loss_per_trade_inr` / risk a share (entry minus stop) |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order_inr` / entry |
| cash | (budget minus the cash buffer) / entry, never more than the cash in `trader/portfolio.json` |

The entry it sizes at: the limit price with `--limit`. For a market order, the plan's
entry, or the price in `trader/prices.json` if it is fresh (under 15 minutes old) and higher.
A price that ran up since the plan means a bigger loss at the same stop, so fewer shares. A
lower price never shrinks the risk.

It refuses, and writes no order, when: the size is zero shares, the order is under the
minimum, reward:risk is under `min_reward_risk`, the stop is not below the entry, the target
is not above it (the move already happened), the plan is for another day, the ticker is
blocked, or the plan is a short. Say the reason to the user in one line.

## Step 3: show the user

Show the four limits, which one decided the size, the shares, the rupees and the max loss at
the stop. Say plainly that a stop is an order, not a promise: in a fast market it can fill
below the stop. Then hand over to `/trader-risk`.

## Example: the reel

RELIANCE on Monday 2026-10-19. Breakout plan: entry 2,500, stop 2,440, target 2,620. Risk ₹60 a
share. The example config: ₹5,00,000 budget, 10% cash buffer, ₹10,000 max loss.

| limit | the math | shares |
| --- | --- | --- |
| max loss | ₹10,000 / ₹60 | **8 (decides it)** |
| position cap | 75% of ₹5,00,000 = ₹3,75,000 / 2,500 | 150 |
| max order | ₹2,00,000 / 2,500 | 80 |
| cash | ₹5,00,000 minus ₹50,000 = ₹4,50,000 / 2,500 | 180 |

8 shares = ₹20,000. Max loss at the stop: 8 x 60 = ₹480. It writes:

```json
{"symbol": "RELIANCE", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
 "order_class": "bracket", "take_profit_limit_price": "2620.00", "stop_loss_stop_price": "2440.00",
 "why": "breakout continuation on RELIANCE: 8 shares, bound by your ₹10,000 max loss per trade (8 x 60 = ₹480 at the stop)",
 "plan": {"entry": 2500.00, "stop": 2440.00, "target": 2620.00, "risk_per_share": 60.00, "max_loss": 480.00,
          "setup": "orb", "entry_time": "10:15 AM", "flat_by": "15:30"}}
```

`why` and `plan` are notes for trader-risk and trader-broker. They are never sent to the
broker. With the stop at 2,300 instead, one share would risk ₹200, more than the ₹10,000 max
loss: no order. At 10:52 the real quote was 2,540, so the same plan sizes to 6 shares at ₹90 a
share, and reward:risk falls to 0.44: refused, because the move it was waiting for has mostly
happened.

## Rules

- Proposals only. This skill never calls a broker tool.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan or the prices. Nothing is guessed.
- No projections: never say what a trade will make. A target is a plan, not a forecast.
- Free market prices are unofficial and can lag. The broker's price is the one that fills.

## What it never does

It never places, approves or schedules an order, never raises a limit on its own, never shrinks a
stop to fit more shares, and never sizes options, margin or short positions.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, leverage, short selling or unauthorized margin positions unless the config allows it and the user confirms.
- Broker keys live in environment variables or the broker connector config, never in the chat.
