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
- `scanner.py` — captures pre-market setups from FMP biggest-gainers
- `simulate.py` — reads today's setups, pulls Yahoo 1-min bars, simulates entry + TP/SL/time exit
- `backtest.py` — one-shot: last-month retro scan using Yahoo 2m bars over a FMP gainers/losers/actives universe
- `data/setups.csv` — captured setups (auto-committed)
- `data/trades.csv` — simulated trade results (auto-committed)

## Run the backtest
```bash
FMP_API_KEY=xxx python backtest.py
```
Keep the strategy definitions in `backtest.py` and `simulate.py` in sync.

## Workflows
- `scan.yml` — runs scanner at 9:00/9:25/9:30/9:35 ET Mon–Fri
- `simulate.yml` — runs simulator at 9:40 ET; supports manual backfill via `workflow_dispatch` with a `date` input

## Local run
```bash
pip install -r requirements.txt
FMP_API_KEY=xxx python scanner.py
```

## Review after 2–3 weeks
Open `data/setups.csv` in Excel. Decide if the edge is real *before* risking money.
