# Indian Day Trader Skill (NSE & BSE)

This repository is the Indian-market version of the original day-trader-skill project. It keeps the same overall architecture, skill layout, and command contracts while adapting the logic for NSE/BSE, IST, INR, and Indian market reporting conventions.

## Current status

This repo is in a validated working state for the current implementation:

- The project structure matches the expected 11-skill layout.
- The Python modules use the standard library only.
- The CLI and JSON contracts are covered by the included tests.
- The repo has been verified with the project’s live unittest suite.

Verified command:

```bash
py -3 -m unittest discover -s tests -v
```

Result from the current validation run: 13 tests ran and all passed.

## What this project adapts

The Indian version preserves the original day-trader-skill behavior while adjusting for Indian market semantics:

- NSE/BSE trading and quoting conventions
- IST timezone handling
- Indian holiday and session logic
- Muhurat and special-session handling
- INR and crore-based financial formatting
- Indian quarterly and FY labeling
- Indian filing and earnings summary conventions

## Project structure

```text
README.md
LICENSE
trader-alerts/
trader-analyst/
trader-broker/
trader-budget/
trader-entry/
trader-exit/
trader-news/
trader-pelosi/
trader-risk/
trader-scanner/
trader-timemachine/
tests/
```

## Included skill modules

- trader-alerts
- trader-analyst
- trader-broker
- trader-budget
- trader-entry
- trader-exit
- trader-news
- trader-pelosi
- trader-risk
- trader-scanner
- trader-timemachine

Each module follows the same repo-wide contract as the original project, but its market logic is specialized for India.

## Quick start

```bash
cd day-trader-skill-main-indian-market

py -3 trader-alerts/alerts.py --help
py -3 trader-analyst/facts.py RELIANCE --json --quarters 2
py -3 -m unittest discover -s tests -v
```

## Design principles

1. Preserve the original repo architecture and command contracts.
2. Replace only the market-specific behavior with Indian equivalents.
3. Keep the implementation dependency-light and standard-library-only.
4. Use deterministic local tests instead of network-dependent drift.
5. Favor contract compatibility with the U.S. repo while adjusting Indian rules.

## Standard-library-only rule

The implementation intentionally avoids third-party data/science libraries such as pandas, numpy, or requests. The project is designed to run with the Python standard library only.

Approved modules include:

- argparse
- csv
- datetime
- gzip
- http.cookiejar
- json
- os
- re
- sys
- time
- urllib

## Notes

This is a repo-level adaptation for Indian market workflows rather than a live brokerage or exchange integration. The code is designed to preserve the original project contract while making the logic appropriate for NSE/BSE operations and Indian market definitions.
