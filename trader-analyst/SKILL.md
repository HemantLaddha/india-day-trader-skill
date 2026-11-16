---
name: trader-analyst
description: >-
  The Earnings Analyst. Reads a company's reported numbers straight from NSE/BSE
  disclosures and annual/quarterly filings, then sums up what changed: revenue,
  gross, operating and net margins, net profit and diluted EPS, quarter by
  quarter, each against the same quarter a year earlier, with the trailing
  twelve months in Indian FY terms. Reads an earnings call transcript when you
  paste one. Use when the user says "how did Reliance's earnings look",
  "analyze the quarterly results", "what changed this quarter", "is revenue
  growing", "check the quarterly filing", "compare margins", "sum up the
  call", "does it report this week", or before trading a stock around its
  earnings.
argument-hint: "[tickers]"
---

# trader-analyst

Earnings move stocks more than anything else on the calendar, and the investor
presentation is written to put the headline number first. This skill reads the
numbers the company actually filed with NSE/BSE or published in its quarterly
results and annual report, lines them up quarter by quarter, and says plainly
what changed. For a day trader it answers two questions before a trade: what did
the last report say, and is the next one inside this trade?

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" --help
```

It needs the exchange or user-agent context the script expects for Indian market
filing sources, and it should refuse to call exchange endpoints without the
required headers or local data.

## What it reads and writes

- Reads listed-company quarter/annual results, company facts and announcement
  files from NSE/BSE-style sources, investor presentation PDFs or web pages,
  and the company’s latest corporate filing or earnings release.
- Writes `trader/metrics.json` with `--metrics`: one row per company (TTM
  revenue, net profit and diluted EPS, latest margins and growth), for your
  notes or a spreadsheet. `metrics.example.json` in this folder is the sample
  format for a working Indian market view.
- Earnings calls: the tool does not fetch transcripts automatically. If the
  user pastes one (or the company’s IR page has it), read it and sum up what
  management said changed: guidance, margins, demand, anything they declined to
  answer.
- The next report date is not always in the exchange data. Look for it in
  `/trader-news` headlines or the company’s investor relations page, and say
  where it came from.

## The rules

- **Filed numbers first.** The table comes from financials the company filed or
  announced. Use the annual report or investor presentation for context
  (guidance, segment colour), and say which numbers came from where.
- **Compare like with like.** Growth is against the same quarter a year
  earlier. Quarter-on-quarter changes are shown but many businesses are seasonal
  (for example, a quarter tied to festival sales or a large export cycle).
- **Say what is derived.** Companies do not always file a standalone quarter in
  the same way across all periods; some trailing or full-year numbers are
  derived or approximated. Mark them clearly as "derived" rather than treating
  them as filed results.
- **Say when the data lags.** Exchange information or filing data can trail a
  filing or investor update. When the newest quarterly filing is later than the
  newest quarter in the facts, the tool prints a note with the source and the
  report link.
- **Flag one-offs.** When net profit is above operating profit, gains outside the
  core business (investment marks, exceptional items, tax adjustments) are inside
  it. The tool should say so. Companies in financial services may show limited
  gross margin; blank is better than zero.

## Steps

1. Run it for the companies in question (or the tickers on
   `trader/watchlist.json`):

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE
   python3 "${CLAUDE_SKILL_DIR}/facts.py" TCS INFY --metrics trader/metrics.json
   ```

   `--quarters 8` shows two years, `--json` everything machine-readable,
   `--cik` or exchange lookup mode when a company does not have a simple ticker.
2. Open the latest earnings presentation or quarterly result and the annual
   report or exchange filing when the numbers need context, and read them.
3. Write the summary: one line on the quarter (revenue, EPS, growth), one on
   margins, one on anything unusual (a one-off, a derived quarter, data that
   lags), and the links. Plain words, real numbers, no adjectives the numbers
   do not support.
4. If the next report falls inside the planned trade (an overnight hold, or a
   result before the open), say it before `/trader-exit` sets the stop: a stop
   does not protect against a gap, the stock can open past it.

## Example: an Indian company

`facts.py RELIANCE` (example run): quarter ending 2026-09-30 (Q2 FY27),
revenue ₹1,024 Cr, +11.2% against a year earlier, net profit ₹220.5 Cr (+15.3%),
diluted EPS ₹12.40 (+13.8%); gross margin 32.1%, operating margin 24.5%, net
margin 21.5%; last four quarters ₹4,000 Cr revenue and ₹48.0 diluted EPS. The
summary flags that net profit includes one-off or exceptional items outside the
core business, so the headline margin discussion must reflect it. The latest
filing date is noted, and the summary ends: "The next report is days away. A day
trade that closes before the bell is not exposed to it; anything held overnight
is."

`facts.py TCS` (example): revenue ₹62,000 Cr, +6.4% against a year earlier,
diluted EPS ₹14.8 (+7.1%). For a company with a large services mix, the tool
notes that exchange filings may lag a little while the company publishes the
quarterly result or investor presentation, so the summary reads those materials
before closing the note.

## What it never does

- Never says a stock is cheap, expensive, a buy or a sell. It reports what the
  company filed.
- Never invents a number the filings do not have, or estimates a quarter it
  cannot derive.
- Never calls exchange endpoints without the expected headers or a valid local
  archive, and stays well under 10 requests a second.

## Safety

Education and tooling, not financial advice. This skill only reads filings.
Nothing places an order except `/trader-broker`, after `/trader-risk` passes and
the user types an explicit yes for that order.
