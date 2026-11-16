---
name: trader-pelosi
description: >-
  The Indian disclosure tracker. Watches public corporate filings and related-party
  disclosures made to SEBI, NSE and BSE, reads the reports as soon as they are
  posted, alerts once per new filing, and turns each document into clean rows
  (who, owner, company, ticker, buy or sell, stake or transaction detail,
  quantity, price range, trade date, filing date, and how many days it took to
  disclose). Flags filings in stocks you hold. Use when the user says "what is
  the promoter buying", "track promoter trades", "did any insider buy X",
  "alert me when a company files", "SEBI disclosure", or "run the Pelosi skill".
argument-hint: "[name] [--read]"
---

# trader-pelosi

In India, public-company disclosures are filed through the exchanges and SEBI.
They are not congressional reports, but they still matter: a promoter, director,
shareholder, or related party filing can change the risk picture long before the
market catches up. This skill reads those public filings, notices the moment a new
one appears, and turns each one into a readable alert.

It is fast. It is not early. A disclosure is usually filed after the event and
sometimes days or weeks later, so by the time the filing is visible the trade or
decision may already be old. There is no inside information here: only public
filings, read quickly. Say that every time.

Tool in this folder (standard library Python; optional local PDF helpers may be
used to read filings locally):

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" --help
```

## What it reads and writes

- Reads public filings from NSE/BSE, SEBI disclosures, and exchange notice feeds
  such as promoter shareholding changes, board changes, pledge updates,
  acquisition and sale notices, rights issues, buybacks, delistings, earnings
  notices, and material events.
- Writes `trader/state/pelosi.json` (the filing IDs already shown, so each alert
  fires once) and keeps downloaded documents in `trader/state/ptr-pdfs/`.
- Reads `trader/portfolio.json` (if it exists) to flag trades or filings in what
  you hold.

## The rules

- **Quote the filing, not a tracker.** Every row comes from the original
  exchange or SEBI filing, with its filing ID and link. Third-party trackers are
  fine for browsing but can be wrong.
- **Amounts are ranges.** "₹1,000,001 - ₹5,000,000", never a guessed exact rupee
  value.
- **Owner matters.** Promoter, promoter group, spouse, family, director, trustee,
  and related party are not the same thing. A filing by a promoter or a family
  entity is different from a director's personal account.
- **Say the delay.** Each row shows how many days passed between the trade and
  the filing; over 45 days is flagged as late.
- **Options are options.** A derivatives contract with strike and expiry is not a
  share purchase. The tool reads contract details and marks exercises separately.

## Step 1: what has been filed

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --member reliance
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --since 2026-10-01        # every company
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --member "HDFC Bank" --year 2025
```

`--member` takes a company name, ticker, or a last name / person name fragment
and repeats. `--type ''` lists every filing type (annual reports and general
notices are still valid entries).

## Step 2: watch for new ones

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" new --member reliance --read
```

Shows only filings not seen at the last check (the first run shows the last 45
days), downloads and reads them with `--read`, and records them in the state
file. Exit code 1 means nothing new. The exchange site updates indexes on a
rolling schedule, so checking every hour on trading days is plenty: run it with
`/loop 1h` or a scheduled task.

## Step 3: read a report

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" fetch 2026112345
python3 "${CLAUDE_SKILL_DIR}/ptr.py" parse ptr.txt --filed 2026-08-21 --json
```

`fetch` saves the PDF or filing document and, if a local PDF text helper is
installed, prints the rows. If it is not installed, open the saved report and
read it directly. `parse` turns the filing text into rows. Check the row count
against the original document when a report runs over several pages.

## Example: a real alert

```
NEW material disclosure: Reliance Industries Limited filed 2026-08-21, filing ID 2026112345
  - promoter group purchase, Reliance Industries Limited equity shares (RELIANCE): 1,50,000 shares
    bought at ₹2,850-₹2,910 per share, filed 28 days after the trade, disclosure flagged as late
```

The same filing may also show a separate pledge disclosure, a promoter group
shareholding update, a board approval, or a rights issue. Then: "This is a
public disclosure filed 28 days after the trade. It says what the promoter group
reported, not what any investor should do next."

If the user wants to act on it, it goes the long way: a disclosure is usually
weeks old, so it is a reason to look at a chart and the price action, not a
setup. `/trader-scanner` and `/trader-entry` decide if there is a trade today;
then shares only (the config has `allow_options: false`), sized by
`/trader-budget`, checked by `/trader-risk`, placed by `/trader-broker` only
after their yes.

## What it never does

- Never says or implies a promoter or insider has confidential information, or
  that copying a related-party trade beats the market. No return claims.
- Never presents a range as an exact rupee figure or a tracker date as a trade
  date.
- Never places an order or copies a derivative trade.
- Never automates login or consent flows for exchange portals.

## Safety

- Education and tooling, not financial advice. Nothing in this pack is a
  recommendation to buy or sell anything.
- Paper trading by default (`"paper": true` in `trader/config.json`).
- Nothing places an order except `/trader-broker`, and only after
  `/trader-risk` passes AND the user types an explicit yes for that order in the
  chat, AND the brokerage tool is set to "Needs approval" in Claude (Customize
  > Connectors > tool permissions) so Claude's own "Allow once / Deny" card
  appears too. Never "Always allow" an order tool.
- No options, margin, shorting or leverage unless the config allows it and the
  user confirms.
- Corporate filings are public disclosures that may be filed days after the
  underlying event. This skill reads them fast; it has no private information,
  and it says so.

## Regulatory note

India's public-company disclosures are governed by SEBI and exchange filing rules,
including promoter and related-party disclosures, material events, and shareholding
updates. This skill behaves as a public-reading tool for the market, not a
source of investment advice or a substitute for the official filing itself.

