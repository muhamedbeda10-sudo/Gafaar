"""Strategy library.

A strategy type maps daily bars to entry/exit signals evaluated at the close.
Signals only ever look at data up to and including their own bar; the
backtester fills them on the NEXT session's open, so there is no look-ahead.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from . import indicators as ind

STRATEGY_TYPES: dict[str, dict] = {
    "sma_cross": {
        "family": "technical",
        "label": "Moving-average crossover",
        "description": "Enter when the fast average crosses above the slow average; exit on the opposite cross.",
        "available": True,
        "params": {
            "fast": {"label": "Fast average (days)", "default": 20, "min": 2, "max": 200},
            "slow": {"label": "Slow average (days)", "default": 50, "min": 3, "max": 400},
        },
    },
    "rsi_reversion": {
        "family": "technical",
        "label": "RSI mean reversion",
        "description": "Enter when RSI recovers above the oversold level; exit when RSI reaches the overbought level.",
        "available": True,
        "params": {
            "period": {"label": "RSI period (days)", "default": 14, "min": 2, "max": 100},
            "oversold": {"label": "Oversold level", "default": 30, "min": 5, "max": 50},
            "overbought": {"label": "Overbought level", "default": 70, "min": 50, "max": 95},
        },
    },
    "macd_cross": {
        "family": "technical",
        "label": "MACD signal crossover",
        "description": "Enter when MACD crosses above its signal line; exit when it crosses below.",
        "available": True,
        "params": {
            "fast": {"label": "Fast EMA", "default": 12, "min": 2, "max": 100},
            "slow": {"label": "Slow EMA", "default": 26, "min": 3, "max": 200},
            "signal": {"label": "Signal EMA", "default": 9, "min": 2, "max": 100},
        },
    },
    "breakout": {
        "family": "momentum",
        "label": "Volume-confirmed breakout",
        "description": "Enter on a close above the prior N-day high with above-average volume; exit on a close below the prior M-day low.",
        "available": True,
        "params": {
            "lookback": {"label": "Breakout lookback (days)", "default": 20, "min": 5, "max": 250},
            "exit_lookback": {"label": "Exit lookback (days)", "default": 10, "min": 2, "max": 250},
            "volume_mult": {"label": "Volume vs 20-day average (x)", "default": 1.5, "min": 0, "max": 10},
        },
    },
    "fundamental_value": {
        "family": "fundamental",
        "label": "Fundamental valuation",
        "description": "Rank by valuation and earnings quality.",
        "available": False,
        "unavailable_reason": "Needs verified financial statements. No fundamental data source is connected yet.",
        "params": {},
    },
    "ai_assisted": {
        "family": "ai",
        "label": "AI-assisted research",
        "description": "Research synthesis and signal explanations.",
        "available": False,
        "unavailable_reason": "Planned for a later phase. AI will explain and rank signals; it will never approve orders on its own.",
        "params": {},
    },
}


class RiskConfig(BaseModel):
    stop_loss_pct: float | None = Field(default=8, gt=0, le=90)
    take_profit_pct: float | None = Field(default=None, gt=0, le=1000)
    max_alloc_pct: float = Field(default=20, gt=0, le=100)  # of equity, per trade
    max_open_positions: int = Field(default=5, ge=1, le=50)
    cash_reserve_pct: float = Field(default=10, ge=0, lt=100)
    slippage_bps: float = Field(default=10, ge=0, le=500)


class StrategyConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    type: str
    params: dict[str, float] = Field(default_factory=dict)
    horizon: Literal["intraday", "swing", "medium_term"] = "swing"
    symbols: list[str] = Field(default_factory=list, max_length=300)
    sectors: list[str] = Field(default_factory=list, max_length=50)
    risk: RiskConfig = Field(default_factory=RiskConfig)

    @model_validator(mode="after")
    def check(self) -> StrategyConfig:
        spec = STRATEGY_TYPES.get(self.type)
        if spec is None:
            raise ValueError(f"unknown strategy type {self.type!r}")
        if not spec["available"]:
            raise ValueError(spec["unavailable_reason"])
        if self.horizon == "intraday":
            raise ValueError("intraday strategies need intraday data, which is not connected yet")
        clean: dict[str, float] = {}
        for key, p in spec["params"].items():
            value = float(self.params.get(key, p["default"]))
            if not p["min"] <= value <= p["max"]:
                raise ValueError(f"{p['label']} must be between {p['min']} and {p['max']}")
            clean[key] = value
        unknown = set(self.params) - set(spec["params"])
        if unknown:
            raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
        if self.type in ("sma_cross", "macd_cross") and clean["fast"] >= clean["slow"]:
            raise ValueError("fast period must be shorter than slow period")
        if self.type == "rsi_reversion" and clean["oversold"] >= clean["overbought"]:
            raise ValueError("oversold level must be below overbought level")
        self.params = clean
        self.symbols = sorted({s.strip().upper() for s in self.symbols if s.strip()})
        return self


def signals(cfg: StrategyConfig, df: pd.DataFrame) -> pd.DataFrame:
    """Boolean `entry` / `exit` columns indexed like df, known at each bar's close."""
    p, close = cfg.params, df["close"]
    if cfg.type == "sma_cross":
        fast, slow = ind.sma(close, int(p["fast"])), ind.sma(close, int(p["slow"]))
        above = fast > slow
        valid = slow.notna()
        entry = above & ~above.shift(1, fill_value=False) & valid & valid.shift(1, fill_value=False)
        exit_ = ~above & above.shift(1, fill_value=False) & valid
    elif cfg.type == "rsi_reversion":
        r = ind.rsi(close, int(p["period"]))
        entry = (r > p["oversold"]) & (r.shift(1) <= p["oversold"])
        exit_ = r >= p["overbought"]
    elif cfg.type == "macd_cross":
        m = ind.macd(close, int(p["fast"]), int(p["slow"]), int(p["signal"]))
        above = m["hist"] > 0
        valid = m["hist"].notna()
        entry = above & ~above.shift(1, fill_value=False) & valid & valid.shift(1, fill_value=False)
        exit_ = ~above & above.shift(1, fill_value=False) & valid
    elif cfg.type == "breakout":
        prior_high = df["high"].rolling(int(p["lookback"])).max().shift(1)
        prior_low = df["low"].rolling(int(p["exit_lookback"])).min().shift(1)
        avg_vol = df["volume"].rolling(20).mean().shift(1)
        entry = (close > prior_high) & (df["volume"] >= p["volume_mult"] * avg_vol)
        exit_ = close < prior_low
    else:  # pragma: no cover - guarded by StrategyConfig validation
        raise ValueError(cfg.type)
    return pd.DataFrame({"entry": entry.fillna(False).astype(bool), "exit": exit_.fillna(False).astype(bool)})
