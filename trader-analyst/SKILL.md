# trader-analyst

Earnings and quarterly results summary for Indian listed companies.

## What it does

- reads company facts and filings from NSE/BSE-style sources
- calculates quarterly revenue, net income and EPS trends
- tracks Indian FY labels with April-to-March fiscal periods
- writes per-ticker metrics rows to `trader/metrics.json`

## CLI

```bash
python3 trader-analyst/facts.py RELIANCE
python3 trader-analyst/facts.py RELIANCE.TCS --json
python3 trader-analyst/facts.py RELIANCE TCS HDFCBANK --metrics trader/metrics.json
```

## Notes

- output uses INR Crores with diluted EPS in rupees
- filing periods follow Indian financial-year logic
- no third-party packages are required
