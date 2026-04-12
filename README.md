# dailytrade

Paper-only pre-market gap scanner. Logs setups to CSV — **no real orders**.

## Strategy
- Gap 20–50% pre-market, float >20M, pm volume >500k, price >$2
- Entry simulated at 9:30:30 ET if first 30s candle is green and breaks pm high
- Exit: +0.5% TP / -0.3% SL / 9:35 time stop

## Setup
1. Get a free key at https://site.financialmodelingprep.com
2. Add it as repo secret `FMP_API_KEY`
3. Workflow runs Mon–Fri at 9:00 / 9:25 / 9:30 / 9:35 ET

## Files
- `scanner.py` — scanner
- `data/setups.csv` — captured setups (auto-committed)
- `data/trades.csv` — simulated trade results (TODO)

## Local run
```bash
pip install -r requirements.txt
FMP_API_KEY=xxx python scanner.py
```

## Review after 2–3 weeks
Open `data/setups.csv` in Excel. Decide if the edge is real *before* risking money.
