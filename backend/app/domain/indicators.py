"""Technical indicators on daily OHLCV frames (pandas)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate daily bars to weekly ('w', weeks ending Thursday) or monthly ('m')."""
    if timeframe == "d":
        return df
    rule = {"w": "W-THU", "m": "ME"}[timeframe]
    agg = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return agg.dropna(subset=["close"])


def support_resistance(df: pd.DataFrame, window: int = 60) -> dict:
    recent = df.tail(window)
    return {"support": float(recent["low"].min()), "resistance": float(recent["high"].max()), "window": len(recent)}


def pct_change_over(close: pd.Series, bars: int) -> float | None:
    if len(close) <= bars:
        return None
    prev = close.iloc[-1 - bars]
    return float(close.iloc[-1] / prev - 1) * 100 if prev else None


def assess(df: pd.DataFrame) -> dict:
    """Rule-based technical and momentum read of the latest bar. Descriptive, not advice."""
    close, vol = df["close"], df["volume"]
    last = float(close.iloc[-1])
    s20, s50, s200 = (sma(close, n).iloc[-1] for n in (20, 50, 200))
    r = rsi(close).iloc[-1]
    m = macd(close).iloc[-1]
    notes: list[str] = []
    score = 0

    def val(x):
        return None if pd.isna(x) else float(x)

    if not pd.isna(s50):
        up = last > s50
        score += 1 if up else -1
        notes.append(f"Price is {'above' if up else 'below'} the 50-day average.")
    if not pd.isna(s50) and not pd.isna(s200):
        up = s50 > s200
        score += 1 if up else -1
        notes.append(f"50-day average is {'above' if up else 'below'} the 200-day average.")
    if not pd.isna(m["hist"]):
        up = m["hist"] > 0
        score += 1 if up else -1
        notes.append(f"MACD is {'above' if up else 'below'} its signal line.")
    if not pd.isna(r):
        if r >= 70:
            notes.append(f"RSI {r:.0f}: overbought zone.")
        elif r <= 30:
            notes.append(f"RSI {r:.0f}: oversold zone.")
        else:
            notes.append(f"RSI {r:.0f}: neutral zone.")
    trend = "uptrend" if score >= 2 else "downtrend" if score <= -2 else "sideways"

    avg_vol = vol.tail(20).mean()
    vol_ratio = float(vol.iloc[-1] / avg_vol) if avg_vol else None
    mom = {k: pct_change_over(close, n) for k, n in (("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126))}
    hi = float(df["high"].tail(252).max())
    mom_notes = []
    if mom["1m"] is not None and mom["3m"] is not None:
        if mom["1m"] > 0 and mom["3m"] > 0:
            mom_label = "positive"
        elif mom["1m"] < 0 and mom["3m"] < 0:
            mom_label = "negative"
        else:
            mom_label = "mixed"
    else:
        mom_label = "insufficient history"
    mom_notes.append(f"{(last / hi - 1) * 100:.1f}% from the high of the last {min(len(df), 252)} sessions.")
    if vol_ratio is not None:
        mom_notes.append(f"Latest volume is {vol_ratio:.1f}x the 20-day average.")
    return {
        "trend": trend,
        "technical_score": score,
        "technical_notes": notes,
        "momentum": mom_label,
        "momentum_notes": mom_notes,
        "returns_pct": mom,
        "volume_ratio": vol_ratio,
        "rsi": val(r),
        "sma20": val(s20),
        "sma50": val(s50),
        "sma200": val(s200),
        "macd_hist": val(m["hist"]),
        **support_resistance(df),
    }
