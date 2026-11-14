"""Market data access: instruments, cached price frames, CSV import, data-quality status."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ..store.sqlite_store import Store
from . import sample
from .calendar import trading_days_between

SEED_FILE = Path(__file__).resolve().parent.parent.parent / "seed" / "egx_instruments.csv"
STALE_AFTER_TRADING_DAYS = 2


class DataError(ValueError):
    pass


class MarketData:
    def __init__(self, store: Store):
        self.store = store
        self._cache_version = -1
        self._frames: dict[str, pd.DataFrame] = {}
        self._sources: dict[str, str] = {}

    # ---- bootstrap -------------------------------------------------------
    def seed_instruments(self) -> None:
        if self.store.list("instruments"):
            return
        with open(SEED_FILE, newline="", encoding="utf-8") as fh, self.store.transaction():
            for row in csv.DictReader(fh):
                self.store.put("instruments", row["symbol"], row)

    def seed_sample_bars(self, days: int, today: date | None = None) -> None:
        if self.store.bar_sources():
            return
        data = sample.generate(self.instruments(include_indices=True), today or date.today(), days)
        with self.store.transaction():
            for symbol, rows in data.items():
                self.store.replace_bars(symbol, rows, "sample")

    # ---- instruments -----------------------------------------------------
    def instruments(self, include_indices: bool = False) -> list[dict]:
        items = self.store.list("instruments")
        return items if include_indices else [i for i in items if i["type"] == "stock"]

    def instrument(self, symbol: str) -> dict | None:
        return self.store.get("instruments", symbol)

    # ---- bars ------------------------------------------------------------
    def _load(self) -> None:
        if self._cache_version == self.store.bars_version:
            return
        rows = self.store.all_bars()
        frames: dict[str, pd.DataFrame] = {}
        sources: dict[str, str] = {}
        if rows:
            df = pd.DataFrame([tuple(r) for r in rows],
                              columns=["symbol", "date", "open", "high", "low", "close", "volume", "source"])
            df["date"] = pd.to_datetime(df["date"])
            for symbol, g in df.groupby("symbol", sort=False):
                sources[symbol] = g["source"].iloc[0]
                frames[symbol] = g.drop(columns=["symbol", "source"]).set_index("date").sort_index()
        self._frames, self._sources = frames, sources
        self._cache_version = self.store.bars_version

    def bars(self, symbol: str) -> pd.DataFrame | None:
        self._load()
        return self._frames.get(symbol)

    def source(self, symbol: str) -> str | None:
        self._load()
        return self._sources.get(symbol)

    def closes(self, symbols: list[str]) -> pd.DataFrame:
        self._load()
        return pd.DataFrame({s: self._frames[s]["close"] for s in symbols if s in self._frames})

    def latest_date(self) -> date | None:
        self._load()
        dates = [f.index[-1] for f in self._frames.values() if len(f)]
        return max(dates).date() if dates else None

    # ---- import ----------------------------------------------------------
    def import_csv(self, symbol: str, content: str, *, name: str | None = None,
                   sector: str | None = None) -> dict:
        symbol = symbol.strip().upper()
        if not symbol.isalnum() or len(symbol) > 12:
            raise DataError("symbol must be 1-12 letters/digits")
        ins = self.instrument(symbol)
        if ins is None and not (name and sector):
            raise DataError(f"unknown symbol {symbol}: provide name and sector to create it")
        reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
        if not reader.fieldnames:
            raise DataError("empty file")
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        missing = [c for c in ("date", "open", "high", "low", "close") if c not in cols]
        if missing:
            raise DataError(f"missing column(s): {', '.join(missing)}. Expected date,open,high,low,close,volume")
        seen: dict[str, tuple] = {}
        for n, row in enumerate(reader, start=2):
            try:
                d = _parse_date(row[cols["date"]])
                o, h, low, c = (float(str(row[cols[k]]).replace(",", "")) for k in ("open", "high", "low", "close"))
                v = float(str(row.get(cols.get("volume", ""), 0) or 0).replace(",", ""))
            except (ValueError, TypeError, KeyError) as exc:
                raise DataError(f"line {n}: {exc}") from None
            if min(o, h, low, c) <= 0 or v < 0:
                raise DataError(f"line {n}: prices must be positive and volume non-negative")
            if h < max(o, c) or low > min(o, c):
                raise DataError(f"line {n}: high/low inconsistent with open/close")
            if d > date.today():
                raise DataError(f"line {n}: date {d} is in the future")
            seen[d.isoformat()] = (d.isoformat(), o, h, low, c, v)
        if len(seen) < 2:
            raise DataError("need at least 2 rows of data")
        rows = [seen[k] for k in sorted(seen)]
        with self.store.transaction():
            if ins is None:
                self.store.put("instruments", symbol,
                               {"symbol": symbol, "name": name.strip(), "sector": sector.strip(), "type": "stock"})
            self.store.replace_bars(symbol, rows, "csv")
        return {"symbol": symbol, "rows": len(rows), "first_date": rows[0][0], "last_date": rows[-1][0]}

    # ---- data quality ----------------------------------------------------
    def status(self, today: date | None = None) -> dict:
        today = today or date.today()
        sources = [dict(r) for r in self.store.bar_sources()]
        latest = self.latest_date()
        age = trading_days_between(latest, today) if latest else None
        names = {s["source"] for s in sources}
        self._load()
        stale_symbols = sorted(
            s for s, f in self._frames.items() if latest and f.index[-1].date() < latest
        )
        missing = sorted(i["symbol"] for i in self.instruments(include_indices=True) if i["symbol"] not in self._frames)
        return {
            "sources": sources,
            "mode": "none" if not names else "sample" if names == {"sample"} else "mixed" if "sample" in names else "imported",
            "has_sample_data": "sample" in names,
            "latest_bar_date": latest.isoformat() if latest else None,
            "trading_days_behind": age,
            "is_stale": bool(age is not None and age > STALE_AFTER_TRADING_DAYS),
            "is_live": False,
            "symbols_behind_latest": stale_symbols,
            "symbols_without_data": missing,
        }


def _parse_date(text: str) -> date:
    text = str(text).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r} (use YYYY-MM-DD)")
