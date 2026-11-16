# trader-exit

Exit planning for Indian market trades.

## Purpose

- set stop-loss and take-profit levels in INR terms
- support bracket-style trade plans before entry
- write `trader/plan.json` for downstream alerts and budgeting

## CLI

```bash
python3 trader-exit/exit.py --stop 1200 --target 1325 --write --json
```
