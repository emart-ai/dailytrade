"""Simulate entry/exit for today's captured setups using Yahoo 1-minute bars.

Strategy (paper, no real orders):
  Pre-market high = max high of all bars before 09:30 ET
  Entry  = close of first 1m bar (09:30-09:31) IF bar is green AND bar.high > pm_high
  Exit   = +0.5% TP / -0.3% SL / 09:35 time stop (whichever first)
  Conservative tie-break: if TP and SL both hit in same bar, assume SL first.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DATA_DIR = Path(__file__).parent / "data"
SETUPS_CSV = DATA_DIR / "setups.csv"
TRADES_CSV = DATA_DIR / "trades.csv"

TP_PCT = 0.005
SL_PCT = 0.003  # applied as 1 - SL_PCT

MARKET_OPEN = time(9, 30)
TIME_STOP = time(9, 35)

TRADE_FIELDS = [
    "date", "symbol", "gap_pct", "pm_high",
    "entry_green", "entry_breaks_pm", "status",
    "entry", "exit", "pnl_pct", "reason",
]


def yahoo_bars(symbol: str) -> list[dict]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1m&range=1d&includePrePost=true"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"[warn] {symbol}: yahoo fetch failed: {e}", file=sys.stderr)
        return []

    r = (data.get("chart", {}).get("result") or [None])[0]
    if not r:
        return []
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    closes = q.get("close") or []
    vols = q.get("volume") or []

    bars = []
    for i in range(len(ts)):
        if None in (opens[i], highs[i], lows[i], closes[i]):
            continue
        bars.append({
            "dt": datetime.fromtimestamp(ts[i], tz=ET),
            "open": opens[i],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
            "volume": vols[i] or 0,
        })
    return bars


def simulate(symbol: str, gap_pct: float, target_date) -> dict | None:
    bars = yahoo_bars(symbol)
    if not bars:
        return None

    day_bars = [b for b in bars if b["dt"].date() == target_date]
    pm_bars = [b for b in day_bars if b["dt"].time() < MARKET_OPEN]
    rth_bars = [b for b in day_bars if MARKET_OPEN <= b["dt"].time() < TIME_STOP]

    if not pm_bars or not rth_bars:
        return None

    pm_high = max(b["high"] for b in pm_bars)
    entry_bar = rth_bars[0]
    is_green = entry_bar["close"] > entry_bar["open"]
    breaks_pm = entry_bar["high"] > pm_high

    base = {
        "date": target_date.isoformat(),
        "symbol": symbol,
        "gap_pct": gap_pct,
        "pm_high": round(pm_high, 4),
        "entry_green": is_green,
        "entry_breaks_pm": breaks_pm,
    }

    if not (is_green and breaks_pm):
        return {**base, "status": "no_entry", "entry": "", "exit": "", "pnl_pct": "", "reason": ""}

    entry_px = entry_bar["close"]
    tp = entry_px * (1 + TP_PCT)
    sl = entry_px * (1 - SL_PCT)

    exit_px = None
    reason = None
    for bar in rth_bars[1:]:
        hit_tp = bar["high"] >= tp
        hit_sl = bar["low"] <= sl
        if hit_tp and hit_sl:
            exit_px, reason = sl, "both_hit_sl"
            break
        if hit_tp:
            exit_px, reason = tp, "tp"
            break
        if hit_sl:
            exit_px, reason = sl, "sl"
            break
    if exit_px is None:
        exit_px = rth_bars[-1]["close"]
        reason = "time_stop"

    pnl = (exit_px - entry_px) / entry_px * 100
    return {
        **base,
        "status": "traded",
        "entry": round(entry_px, 4),
        "exit": round(exit_px, 4),
        "pnl_pct": round(pnl, 3),
        "reason": reason,
    }


def load_setups_for(target_date) -> list[dict]:
    if not SETUPS_CSV.exists():
        return []
    want = target_date.isoformat()
    seen: set[str] = set()
    out: list[dict] = []
    with SETUPS_CSV.open() as f:
        for row in csv.DictReader(f):
            if row["date"] != want or row["symbol"] in seen:
                continue
            seen.add(row["symbol"])
            out.append(row)
    return out


def already_simulated(target_date) -> set[str]:
    if not TRADES_CSV.exists():
        return set()
    want = target_date.isoformat()
    done: set[str] = set()
    with TRADES_CSV.open() as f:
        for row in csv.DictReader(f):
            if row.get("date") == want:
                done.add(row["symbol"])
    return done


def append_trade(row: dict) -> None:
    new_file = not TRADES_CSV.exists()
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TRADES_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in TRADE_FIELDS})


def main() -> int:
    # Allow override for backfill / testing: SIMULATE_DATE=YYYY-MM-DD
    override = os.environ.get("SIMULATE_DATE")
    target_date = (
        datetime.fromisoformat(override).date() if override
        else datetime.now(ET).date()
    )

    setups = load_setups_for(target_date)
    if not setups:
        print(f"[info] no setups for {target_date}")
        return 0

    done = already_simulated(target_date)
    pending = [s for s in setups if s["symbol"] not in done]
    print(f"[info] {target_date}: {len(setups)} setup(s), {len(pending)} pending, {len(done)} already done")

    for s in pending:
        result = simulate(s["symbol"], float(s["gap_pct"]), target_date)
        if result is None:
            print(f"  {s['symbol']}: no bars")
            continue
        print(
            f"  {result['symbol']}: {result['status']} "
            f"{result.get('reason') or ''} pnl={result.get('pnl_pct')}"
        )
        append_trade(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
