"""Pre-market gap scanner — logs simulated gap-and-go trades to CSV.

Strategy (paper, no real orders):
  Setup at 09:25 ET — gap 20-50%, float >20M, pm volume >500k, price >$2, above pm VWAP
  Entry  at 09:30:30 — first 30s candle green and breaks pm high
  Exit   — +0.5% TP / -0.3% SL / 09:35 time stop
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

FMP_KEY = os.environ.get("FMP_API_KEY")
FMP_BASE = "https://financialmodelingprep.com/api/v3"
DATA_DIR = Path(__file__).parent / "data"
SETUPS_CSV = DATA_DIR / "setups.csv"
TRADES_CSV = DATA_DIR / "trades.csv"

ET = ZoneInfo("America/New_York")

GAP_MIN_PCT = 20.0
GAP_MAX_PCT = 50.0
MIN_FLOAT = 20_000_000
MIN_PM_VOLUME = 500_000
MIN_PRICE = 2.0
TP_PCT = 0.005
SL_PCT = -0.003


@dataclass
class Setup:
    date: str
    symbol: str
    prev_close: float
    pm_price: float
    gap_pct: float
    pm_volume: int
    float_shares: int
    captured_at: str
    phase: str  # "pre_open" | "entry" | "exit"


def fmp_get(path: str, **params):
    if not FMP_KEY:
        raise RuntimeError("FMP_API_KEY not set")
    params["apikey"] = FMP_KEY
    r = requests.get(f"{FMP_BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_premarket_gainers() -> list[dict]:
    """FMP gainers reflects pre-market when called before open."""
    return fmp_get("/stock_market/gainers")


def fetch_profile(symbol: str) -> dict | None:
    data = fmp_get(f"/profile/{symbol}")
    return data[0] if data else None


def fetch_quote(symbol: str) -> dict | None:
    data = fmp_get(f"/quote/{symbol}")
    return data[0] if data else None


def scan_setups() -> list[Setup]:
    now = datetime.now(ET)
    today = now.date().isoformat()
    captured = now.isoformat(timespec="seconds")

    try:
        gainers = fetch_premarket_gainers()
    except Exception as e:
        print(f"[error] gainers fetch failed: {e}", file=sys.stderr)
        return []

    setups: list[Setup] = []
    for g in gainers:
        symbol = g.get("symbol")
        change_pct = g.get("changesPercentage")
        price = g.get("price")
        if not symbol or change_pct is None or price is None:
            continue
        if not (GAP_MIN_PCT <= change_pct <= GAP_MAX_PCT):
            continue
        if price < MIN_PRICE:
            continue

        try:
            profile = fetch_profile(symbol)
            quote = fetch_quote(symbol)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)
            continue
        if not profile or not quote:
            continue

        float_shares = profile.get("floatShares") or quote.get("sharesOutstanding") or 0
        pm_volume = quote.get("volume") or 0
        prev_close = quote.get("previousClose") or 0

        if float_shares < MIN_FLOAT or pm_volume < MIN_PM_VOLUME:
            continue

        setups.append(
            Setup(
                date=today,
                symbol=symbol,
                prev_close=prev_close,
                pm_price=price,
                gap_pct=round(change_pct, 2),
                pm_volume=int(pm_volume),
                float_shares=int(float_shares),
                captured_at=captured,
                phase=os.environ.get("SCAN_PHASE", "pre_open"),
            )
        )

    return setups


def append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    setups = scan_setups()
    print(f"[info] {datetime.now(ET).isoformat(timespec='seconds')} — {len(setups)} setup(s)")
    for s in setups:
        print(f"  {s.symbol}  gap={s.gap_pct}%  px={s.pm_price}  pmVol={s.pm_volume:,}  float={s.float_shares:,}")
    append_csv(SETUPS_CSV, [asdict(s) for s in setups])
    return 0


if __name__ == "__main__":
    sys.exit(main())
