"""1-month backtest of paper strategies against a current-universe proxy.

Universe  = FMP biggest-gainers + biggest-losers + most-actives
            (currently-volatile names — biased, but the set most likely to have gapped in the last month)
Data      = Yahoo 2m bars (range=1mo, includePrePost). Volume in pre-market bars is unreliable;
            we use the first-RTH-bar volume as the liquidity proxy.
Strategies = same definitions as simulate.py — keep these two in sync if you tune them.

Usage:
    FMP_API_KEY=xxx python backtest.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
FMP_KEY = os.environ.get("FMP_API_KEY")

STRATEGIES = [
    {"name": "A", "tp": 0.005, "sl": 0.003, "time_stop": dtime(9, 35)},
    {"name": "B", "tp": 0.015, "sl": 0.010, "time_stop": dtime(9, 45)},
]
MARKET_OPEN = dtime(9, 30)
GAP_MIN, GAP_MAX = 10.0, 50.0
MIN_PRICE = 2.0
MIN_OPEN_VOLUME = 100_000


def fmp(path: str):
    if not FMP_KEY:
        raise RuntimeError("FMP_API_KEY not set")
    url = f"https://financialmodelingprep.com/stable{path}?apikey={FMP_KEY}"
    return json.loads(urllib.request.urlopen(url, timeout=20).read())


def yahoo_bars(symbol: str, interval: str = "2m", rng: str = "1mo") -> list[dict]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval={interval}&range={rng}&includePrePost=true"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception:
        return []
    r = (data.get("chart", {}).get("result") or [None])[0]
    if not r:
        return []
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    o = q.get("open") or []
    h = q.get("high") or []
    l = q.get("low") or []
    c = q.get("close") or []
    v = q.get("volume") or []
    bars = []
    for i in range(len(ts)):
        if None in (o[i], h[i], l[i], c[i]):
            continue
        bars.append({
            "dt": datetime.fromtimestamp(ts[i], tz=ET),
            "o": o[i], "h": h[i], "l": l[i], "c": c[i], "v": v[i] or 0,
        })
    return bars


def build_universe() -> list[str]:
    syms: set[str] = set()
    for path in ("/biggest-gainers", "/biggest-losers", "/most-actives"):
        try:
            for g in fmp(path):
                syms.add(g["symbol"])
        except Exception as e:
            print(f"[warn] {path}: {e}", file=sys.stderr)
    return sorted(syms)


def simulate_day(rth_bars: list[dict], pm_high: float, strat: dict) -> dict:
    entry_bar = rth_bars[0]
    is_green = entry_bar["c"] > entry_bar["o"]
    breaks = entry_bar["h"] > pm_high
    if not (is_green and breaks):
        return {"status": "no_entry", "entry": None, "exit": None, "pnl_pct": None, "reason": None}

    entry = entry_bar["c"]
    tp = entry * (1 + strat["tp"])
    sl = entry * (1 - strat["sl"])

    exit_px = None
    reason = None
    for b in rth_bars[1:]:
        if b["h"] >= tp and b["l"] <= sl:
            exit_px, reason = sl, "both_hit_sl"
            break
        if b["h"] >= tp:
            exit_px, reason = tp, "tp"
            break
        if b["l"] <= sl:
            exit_px, reason = sl, "sl"
            break
    if exit_px is None:
        exit_px = rth_bars[-1]["c"]
        reason = "time_stop"

    return {
        "status": "traded",
        "entry": round(entry, 4),
        "exit": round(exit_px, 4),
        "pnl_pct": round((exit_px - entry) / entry * 100, 3),
        "reason": reason,
    }


def main() -> int:
    universe = build_universe()
    print(f"universe: {len(universe)} tickers\n")
    all_trades: list[dict] = []
    setups_found = 0

    for i, sym in enumerate(universe, 1):
        bars = yahoo_bars(sym)
        if not bars:
            continue
        by_date: dict = defaultdict(list)
        for b in bars:
            by_date[b["dt"].date()].append(b)
        dates = sorted(by_date.keys())

        for d_idx in range(1, len(dates)):
            d = dates[d_idx]
            prev_d = dates[d_idx - 1]
            prev_rth = [b for b in by_date[prev_d] if MARKET_OPEN <= b["dt"].time() < dtime(16, 0)]
            if not prev_rth:
                continue
            prev_close = prev_rth[-1]["c"]
            if prev_close <= 0:
                continue

            day_bars = by_date[d]
            pm_bars = [b for b in day_bars if b["dt"].time() < MARKET_OPEN]
            if not pm_bars:
                continue
            pm_high = max(b["h"] for b in pm_bars)

            rth_all = [b for b in day_bars if MARKET_OPEN <= b["dt"].time() < dtime(16, 0)]
            if not rth_all:
                continue
            open_px = rth_all[0]["o"]
            open_vol = rth_all[0]["v"]

            gap_pct = (pm_high - prev_close) / prev_close * 100
            open_gap_pct = (open_px - prev_close) / prev_close * 100

            if not (GAP_MIN <= gap_pct <= GAP_MAX):
                continue
            if open_px < MIN_PRICE:
                continue
            if open_vol < MIN_OPEN_VOLUME:
                continue

            setups_found += 1
            for strat in STRATEGIES:
                rth_window = [b for b in day_bars if MARKET_OPEN <= b["dt"].time() < strat["time_stop"]]
                if not rth_window:
                    continue
                res = simulate_day(rth_window, pm_high, strat)
                all_trades.append({
                    "date": d.isoformat(),
                    "symbol": sym,
                    "strategy": strat["name"],
                    "gap_pct": round(gap_pct, 2),
                    "open_gap_pct": round(open_gap_pct, 2),
                    "pm_high": round(pm_high, 4),
                    **res,
                })

        if i % 20 == 0:
            print(f"  ...scanned {i}/{len(universe)}  setups so far: {setups_found}")

    print(f"\nTotal qualifying setups: {setups_found}")
    print(f"Total trade rows: {len(all_trades)}\n")

    for strat_name in [s["name"] for s in STRATEGIES]:
        rows = [t for t in all_trades if t["strategy"] == strat_name]
        traded = [t for t in rows if t["status"] == "traded"]
        no_entry = [t for t in rows if t["status"] == "no_entry"]
        tps = [t for t in traded if t["reason"] == "tp"]
        sls = [t for t in traded if t["reason"] == "sl"]
        boths = [t for t in traded if t["reason"] == "both_hit_sl"]
        tss = [t for t in traded if t["reason"] == "time_stop"]
        total_pnl = sum(t["pnl_pct"] for t in traded)
        print(f"=== Strategy {strat_name} ===")
        print(f"  setups:       {len(rows)}")
        print(f"  no_entry:     {len(no_entry)}  ({len(no_entry)/max(len(rows),1)*100:.0f}%)")
        print(f"  traded:       {len(traded)}")
        print(f"    tp (clean):      {len(tps)}")
        print(f"    sl (clean):      {len(sls)}")
        print(f"    both_hit_sl:     {len(boths)}")
        print(f"    time_stop:       {len(tss)}")
        if traded:
            wins = sum(1 for t in traded if t["pnl_pct"] > 0)
            print(f"  win rate:     {wins/len(traded)*100:.1f}%")
            print(f"  avg pnl:      {total_pnl/len(traded):+.3f}%")
            print(f"  total pnl:    {total_pnl:+.2f}%  (sum of %, not compounded)")
        print()

    print("=== All trades ===")
    for t in sorted(all_trades, key=lambda x: (x["date"], x["symbol"], x["strategy"])):
        pnl = t.get("pnl_pct")
        pnl_s = f"{pnl:+.2f}%" if pnl is not None else "  --"
        print(
            f"  {t['date']}  {t['symbol']:<6}  {t['strategy']}  "
            f"pm={t['gap_pct']:>5.1f}%  open={t['open_gap_pct']:>5.1f}%  "
            f"{t['status']:<9}  {str(t.get('reason') or ''):<14}  {pnl_s}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
