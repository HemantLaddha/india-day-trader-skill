# trader-budget

Budgeting and position sizing for Indian equity trades.

## Purpose

- size a position in INR using max-drawdown assumptions
- align with daily budget rules and account limits
- output a structured order recommendation for downstream risk checks

## CLI

```bash
python3 trader-budget/size.py --capital 200000 --risk 2000 --price 1200 --json
```
