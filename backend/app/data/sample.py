"""Deterministic SAMPLE price generator.

These are synthetic random walks, NOT market prices. They exist so every screen
and the backtester can be exercised before a real data feed is connected. Bars
written by this module carry source='sample' and the UI labels them as such.
"""
from __future__ import annotations

import zlib
from datetime import date

import numpy as np

from .calendar import last_trading_days


def _seed(text: str) -> int:
    return zlib.crc32(text.encode())


def generate(instruments: list[dict], end: date, days: int) -> dict[str, list[tuple]]:
    dates = [d.isoformat() for d in last_trading_days(end, days)]
    n = len(dates)
    market = np.random.default_rng(_seed("market")).normal(0.0004, 0.009, n)
    sector_factor: dict[str, np.ndarray] = {}
    out: dict[str, list[tuple]] = {}
    for ins in instruments:
        sym, sector = ins["symbol"], ins["sector"]
        rng = np.random.default_rng(_seed(sym))
        if sector not in sector_factor:
            sector_factor[sector] = np.random.default_rng(_seed("sector:" + sector)).normal(0.0, 0.007, n)
        if ins["type"] == "index":
            rets = market + rng.normal(0, 0.002, n)
            start = {"EGX30": 30000.0, "EGX70": 9000.0, "EGX100": 12500.0}.get(sym, 10000.0)
            base_vol = 0.0
        else:
            beta = rng.uniform(0.6, 1.4)
            # slow regime drift so trend strategies have something to find
            regime = np.repeat(rng.normal(0.0, 0.0012, n // 40 + 1), 40)[:n]
            rets = beta * market + sector_factor[sector] + regime + rng.normal(0, rng.uniform(0.010, 0.022), n)
            start = float(rng.uniform(2.0, 90.0))
            base_vol = float(rng.uniform(2e5, 6e6))
        close = start * np.exp(np.cumsum(rets))
        prev = np.concatenate([[start], close[:-1]])
        open_ = prev * np.exp(rng.normal(0, 0.004, n))
        spread = np.abs(rng.normal(0, 0.008, n))
        high = np.maximum(open_, close) * (1 + spread)
        low = np.minimum(open_, close) * (1 - spread)
        volume = base_vol * np.exp(rng.normal(0, 0.5, n)) * (1 + 8 * np.abs(rets)) if base_vol else np.zeros(n)
        out[sym] = [
            (dates[i], round(float(open_[i]), 2), round(float(high[i]), 2), round(float(low[i]), 2),
             round(float(close[i]), 2), float(int(volume[i])))
            for i in range(n)
        ]
    return out
