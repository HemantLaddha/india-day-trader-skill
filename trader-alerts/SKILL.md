# trader-alerts

Price alerts and the NSE/BSE market clock for Indian equities.

## What it does

- watches stop-loss, target and price-change alerts
- tracks `opening_bell` and `time` rules in IST
- reads helper quotes from Yahoo Finance `.NS` / `.BO` symbols
- stores alert state in `trader/state/alerts.json`
- supports offline fixtures for deterministic tests

## CLI

```bash
python3 trader-alerts/alerts.py clock
python3 trader-alerts/alerts.py quote RELIANCE --write
python3 trader-alerts/alerts.py add --from-plan
python3 trader-alerts/alerts.py check --offline tests/fixtures/trader-alerts
```

## Notes

- Market hours are in IST: 09:15 to 15:30
- Special Muhurat sessions are supported
- Data is free, delayed and unofficial; use broker prices for execution
