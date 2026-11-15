# The Indian Day Trader skill (NSE & BSE)

Claude skills adapted for Indian day trading across NSE/BSE charts, breaking news, entry/exit timing, and risk simulations, using free public Python tools (`.NS` / `.BO` data). 

> **Upstream attribution:** Adapted for the Indian market (NSE/BSE) from Jake Schincariol's original [day-trader-skill](https://github.com).

## Install

Install via Claude or Claude Code plugin marketplace, or clone the repository directly into your Claude skills directory. Requirements: Python 3.8+ (no `pip install` required).

## The eleven skills

| Command | Job | What it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans NSE/BSE charts for opening-range breakouts (09:15–09:30 IST), flags, and oversold bounces. |
| `/trader-news` | News Monitor | Tracks breaking news and corporate exchange announcements for watched stocks. |
| `/trader-entry` | Entry Timer | Monitors setup bars in IST to pinpoint entry timing. |
| `/trader-exit` | Exit Planner | Pre-calculates stop-loss and targets in INR prior to entry. |
| `/trader-timemachine` | Time Machine | Replays historical and simulated trade sessions to evaluate statistical odds. |
| `/trader-risk` | Risk Manager | Enforces SEBI peak margins, max loss caps, and daily trading limits. |
| `/trader-budget` | Budget Manager | Sizes INR positions relative to account capital and risk limits. |
| `/trader-broker` | Order Executor | Routes approved orders to Indian broker connectors (defaulting to paper trading). |
| `/trader-alerts` | Price Alerts | Triggers alerts for price targets, stop-losses, and the 09:15 IST opening bell. |
| `/trader-analyst` | Earnings Analyst | Summarizes SEBI Regulation 33 quarterly results (YoY/QoQ, FY Apr–Mar). |
| `/trader-pelosi` | Bulk & Block Deal Tracker | Monitors NSE/BSE bulk/block deals and insider (PIT) disclosures. |

## Example workflow (`RELIANCE.NS`)

An end-to-end trade flow on Monday, October 19, 2026:
1. **Scanner & News**: Identifies a breakout on `RELIANCE.NS` above its 09:15–09:30 IST opening range alongside morning network expansion news.
2. **Entry & Exit**: `/trader-entry` confirms the 5-minute candle trigger while `/trader-exit` maps the stop-loss and target levels.
3. **Time Machine & Budget**: Runs 10,000 session simulations and sizes a 222-share position for a ₹2,00,000 account with a ₹2,000 max loss.
4. **Risk, Broker & Alerts**: Validates SEBI peak margins via `/trader-risk`, awaits user confirmation for execution via `/trader-broker`, and arms session monitors via `/trader-alerts` (including a 15:15 IST flat reminder).

## Fine print

* **Not SEBI-registered advice**: Open-source software running public data arithmetic; day trading carries substantial financial risk.
* **Manual confirmation required**: Trades execute only upon explicit user authorization; paper trading is enabled by default (`"paper": true`).
* **Indian Market Mechanics**: Regular equity hours run **09:15 to 15:30 IST** (pre-open 09:00–09:15 IST). There is no $25,000 PDT rule (`"pdt_guard": false`), though brokers enforce strict **SEBI peak margin** requirements and auto-square off MIS positions around **15:15–15:20 IST**.
* **Taxation**: Intraday equity gains are classified as speculative business income under the Indian Income Tax Act; account for STT, GST, stamp duty, and exchange fees.

For complete directory structures and command flags, refer to the repository files.
