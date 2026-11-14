"""Application services: glue between the store, market data and the domain rules."""
from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from .config import Settings
from .data.market import MarketData
from .domain import indicators as ind
from .domain.backtest import run_backtest
from .domain.fees import DEFAULT_FEE_SCHEDULE, FeeSchedule, compute_fees
from .domain.ledger import LedgerError, build_trade, replay
from .domain.money import ZERO, D, f, money
from .domain.strategies import StrategyConfig, signals
from .store.sqlite_store import Store


class NotFound(LookupError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean(obj):
    """Make a structure JSON-safe: NaN/inf -> None, Decimal -> float, Timestamp -> date string."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if hasattr(obj, "item"):  # numpy scalar
        return clean(obj.item())
    return obj


class App:
    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings
        self.market = MarketData(store)
        self._quotes_version = -1
        self._quotes: pd.DataFrame | None = None

    # ---- bootstrap -------------------------------------------------------
    def bootstrap(self) -> None:
        self.market.seed_instruments()
        if self.settings.seed_sample_data:
            self.market.seed_sample_bars(self.settings.sample_history_days)
        if self.store.get("settings", "fees") is None:
            self.store.put("settings", "fees", DEFAULT_FEE_SCHEDULE.model_dump(mode="json"))
        if self.store.get("settings", "app") is None:
            with self.store.transaction():
                self.store.put("settings", "app", {
                    "starting_capital": str(self.settings.initial_capital_egp),
                    "currency": "EGP",
                    "benchmark": "EGX30",
                    "active_portfolio_id": None,
                })
                self._new_portfolio(self.settings.initial_capital_egp, reason="initial")

    def audit(self, action: str, entity: str, detail: dict | None = None) -> None:
        self.store.append("audit", {"ts": now_iso(), "action": action, "entity": entity, "detail": detail or {}})

    # ---- settings --------------------------------------------------------
    def app_settings(self) -> dict:
        return self.store.get("settings", "app")

    def update_app_settings(self, *, starting_capital: Decimal | None, benchmark: str | None) -> dict:
        with self.store.transaction():
            cur = self.app_settings()
            before = dict(cur)
            if starting_capital is not None:
                cur["starting_capital"] = str(money(starting_capital))
            if benchmark is not None:
                ins = self.market.instrument(benchmark)
                if ins is None:
                    raise NotFound(f"unknown benchmark {benchmark}")
                cur["benchmark"] = benchmark
            self.store.put("settings", "app", cur)
            self.audit("update", "settings", {"before": before, "after": cur})
            return cur

    def fee_schedule(self) -> FeeSchedule:
        return FeeSchedule.model_validate(self.store.get("settings", "fees"))

    def update_fee_schedule(self, schedule: FeeSchedule) -> FeeSchedule:
        with self.store.transaction():
            before = self.store.get("settings", "fees")
            after = schedule.model_dump(mode="json")
            self.store.put("settings", "fees", after)
            self.audit("update", "fee_schedule", {"before": before, "after": after})
        return schedule

    # ---- quotes ----------------------------------------------------------
    def quotes(self) -> pd.DataFrame:
        """Latest quote row per stock, with short-term returns."""
        if self._quotes is not None and self._quotes_version == self.store.bars_version:
            return self._quotes
        rows = []
        for insx in self.market.instruments(include_indices=True):
            df = self.market.bars(insx["symbol"])
            if df is None or len(df) == 0:
                continue
            close = df["close"]
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) > 1 else None
            rows.append({
                "symbol": insx["symbol"], "name": insx["name"], "sector": insx["sector"], "type": insx["type"],
                "last": last,
                "change": last - prev if prev else None,
                "change_pct": (last / prev - 1) * 100 if prev else None,
                "week_pct": ind.pct_change_over(close, 5),
                "month_pct": ind.pct_change_over(close, 21),
                "volume": float(df["volume"].iloc[-1]),
                "avg_volume_20": float(df["volume"].tail(20).mean()),
                "turnover": last * float(df["volume"].iloc[-1]),
                "as_of": df.index[-1].strftime("%Y-%m-%d"),
                "source": self.market.source(insx["symbol"]),
                "spark": [round(float(v), 2) for v in close.tail(30)],
            })
        self._quotes = pd.DataFrame(rows)
        self._quotes_version = self.store.bars_version
        return self._quotes

    def _records(self, df: pd.DataFrame) -> list[dict]:
        return clean(df.astype(object).where(df.notna(), None).to_dict("records"))

    def stock_rows(self, sector: str | None = None, q: str | None = None, category: str | None = None) -> list[dict]:
        df = self.quotes()
        if df.empty:
            return []
        df = df[df["type"] == "stock"]
        if sector:
            df = df[df["sector"] == sector]
        if category:
            cat = self.store.get("categories", category)
            if cat is None:
                raise NotFound("category not found")
            df = df[df["symbol"].isin(cat["symbols"])]
        if q:
            ql = q.lower()
            df = df[df["symbol"].str.lower().str.contains(ql, regex=False) | df["name"].str.lower().str.contains(ql, regex=False)]
        watch = {w["symbol"] for w in self.store.list("watchlist")}
        out = self._records(df.sort_values("symbol"))
        for r in out:
            r["watched"] = r["symbol"] in watch
        return out

    def market_overview(self) -> dict:
        df = self.quotes()
        if df.empty:
            return {"indices": [], "breadth": None, "gainers": [], "losers": [], "most_active": []}
        stocks = df[df["type"] == "stock"]
        latest = stocks["as_of"].max()
        current = stocks[(stocks["as_of"] == latest) & stocks["change_pct"].notna()]
        cols = ["symbol", "name", "sector", "last", "change_pct", "volume", "turnover"]
        return {
            "as_of": latest,
            "indices": self._records(df[df["type"] == "index"][["symbol", "name", "last", "change", "change_pct", "as_of", "source", "spark"]]),
            "breadth": {
                "covered": int(len(stocks)),
                "advancers": int((current["change_pct"] > 0).sum()),
                "decliners": int((current["change_pct"] < 0).sum()),
                "unchanged": int((current["change_pct"] == 0).sum()),
                "volume": float(current["volume"].sum()),
                "turnover_approx": float(current["turnover"].sum()),
                "avg_change_pct": float(current["change_pct"].mean()) if len(current) else None,
            },
            "gainers": self._records(current.nlargest(5, "change_pct")[cols]),
            "losers": self._records(current.nsmallest(5, "change_pct")[cols]),
            "most_active": self._records(current.nlargest(5, "volume")[cols]),
        }

    def sectors(self) -> list[dict]:
        df = self.quotes()
        if df.empty:
            return []
        stocks = df[df["type"] == "stock"]
        market_month = stocks["month_pct"].mean()
        out = []
        for sector, g in stocks.groupby("sector"):
            ranked = g.dropna(subset=["change_pct"]).sort_values("change_pct")
            month = g["month_pct"].mean()
            out.append({
                "sector": sector,
                "stocks": int(len(g)),
                "day_pct": g["change_pct"].mean(),
                "week_pct": g["week_pct"].mean(),
                "month_pct": month,
                "avg_volume": g["avg_volume_20"].mean(),
                "turnover_approx": g["turnover"].sum(),
                "best": None if ranked.empty else {"symbol": ranked.iloc[-1]["symbol"], "change_pct": ranked.iloc[-1]["change_pct"]},
                "worst": None if ranked.empty else {"symbol": ranked.iloc[0]["symbol"], "change_pct": ranked.iloc[0]["change_pct"]},
                "relative_strength": month - market_month if pd.notna(month) and pd.notna(market_month) else None,
            })
        return clean(sorted(out, key=lambda r: (r["month_pct"] is None, -(r["month_pct"] or 0))))

    def stock_detail(self, symbol: str, timeframe: str = "d", limit: int = 500) -> dict:
        symbol = symbol.upper()
        insx = self.market.instrument(symbol)
        if insx is None:
            raise NotFound(f"unknown symbol {symbol}")
        daily = self.market.bars(symbol)
        if daily is None or len(daily) < 2:
            return {"instrument": insx, "has_data": False}
        df = ind.resample(daily, timeframe)
        close = df["close"]
        m = ind.macd(close)
        frame = pd.DataFrame({
            "time": df.index.strftime("%Y-%m-%d"),
            "open": df["open"].values, "high": df["high"].values, "low": df["low"].values,
            "close": close.values, "volume": df["volume"].values,
            "sma20": ind.sma(close, 20).values, "sma50": ind.sma(close, 50).values,
            "sma200": ind.sma(close, 200).values, "rsi": ind.rsi(close).values,
            "macd": m["macd"].values, "macd_signal": m["signal"].values, "macd_hist": m["hist"].values,
        }).tail(limit)
        q = self.quotes()
        quote = self._records(q[q["symbol"] == symbol].drop(columns=["spark"]))[0]
        return clean({
            "instrument": insx,
            "has_data": True,
            "quote": quote,
            "watched": self.store.get("watchlist", symbol) is not None,
            "timeframe": timeframe,
            "bars": self._records(frame),
            "assessment": ind.assess(daily),
            "fundamentals": {
                "available": False,
                "reason": "No verified fundamental data source is connected yet (financial statements, EPS, P/E, dividends).",
            },
            "data_note": "SAMPLE DATA - synthetic prices, not market quotes." if quote["source"] == "sample" else None,
        })

    # ---- watchlist & categories -----------------------------------------
    def set_watch(self, symbol: str, on: bool) -> None:
        symbol = symbol.upper()
        if self.market.instrument(symbol) is None:
            raise NotFound(f"unknown symbol {symbol}")
        if on:
            self.store.put("watchlist", symbol, {"symbol": symbol, "added_at": now_iso()})
        else:
            self.store.delete("watchlist", symbol)

    def watchlist(self) -> list[dict]:
        symbols = [w["symbol"] for w in self.store.list("watchlist")]
        return [r for r in self.stock_rows() if r["symbol"] in symbols]

    def save_category(self, name: str, symbols: list[str], id: str | None = None) -> dict:
        known = {i["symbol"] for i in self.market.instruments()}
        symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        unknown = [s for s in symbols if s not in known]
        if unknown:
            raise NotFound(f"unknown symbol(s): {', '.join(unknown)}")
        if id is not None and self.store.get("categories", id) is None:
            raise NotFound("category not found")
        doc = {"id": id or uuid.uuid4().hex[:12], "name": name.strip(), "symbols": symbols}
        with self.store.transaction():
            self.store.put("categories", doc["id"], doc)
            self.audit("save", "category", doc)
        return doc

    # ---- portfolio -------------------------------------------------------
    def _new_portfolio(self, capital, reason: str) -> dict:
        pid = uuid.uuid4().hex[:12]
        capital = money(capital)
        if capital <= 0:
            raise LedgerError("starting capital must be positive")
        doc = {"id": pid, "created_at": now_iso(), "starting_capital": str(capital), "mode": "paper"}
        self.store.put("portfolios", pid, doc)
        self.store.append(f"ledger:{pid}", {"type": "DEPOSIT", "amount": str(capital), "ts": now_iso(),
                                             "trade_date": None, "note": "Starting paper capital"})
        cfg = self.app_settings()
        cfg["active_portfolio_id"] = pid
        self.store.put("settings", "app", cfg)
        self.audit("create", "portfolio", {**doc, "reason": reason})
        return doc

    def reset_portfolio(self) -> dict:
        """Start a fresh paper portfolio. The previous ledger is kept, never deleted."""
        with self.store.transaction():
            return self._new_portfolio(D(self.app_settings()["starting_capital"]), reason="reset")

    def _ledger_coll(self) -> str:
        return f"ledger:{self.app_settings()['active_portfolio_id']}"

    def _price_on(self, symbol: str, trade_date: str | None) -> tuple[Decimal, str]:
        df = self.market.bars(symbol)
        if df is None or len(df) == 0:
            raise LedgerError(f"no price data for {symbol}")
        if trade_date is None:
            return D(float(df["close"].iloc[-1])), df.index[-1].strftime("%Y-%m-%d")
        ts = pd.Timestamp(trade_date)
        if ts not in df.index:
            raise LedgerError(f"{symbol} has no bar on {trade_date} (not a session, or data missing)")
        return D(float(df.loc[ts, "close"])), trade_date

    def preview_trade(self, side: str, symbol: str, qty: int, trade_date: str | None) -> dict:
        symbol = symbol.upper()
        if self.market.instrument(symbol) is None or self.market.instrument(symbol)["type"] != "stock":
            raise NotFound(f"unknown stock {symbol}")
        price, used_date = self._price_on(symbol, trade_date)
        state = replay(self.store.list(self._ledger_coll()))
        schedule = self.fee_schedule()
        gross = money(price * qty)
        fees = compute_fees(schedule, side.lower(), gross)
        error = None
        try:
            build_trade(state, schedule, side=side, symbol=symbol, qty=qty, price=price)
        except LedgerError as exc:
            error = str(exc)
        held = state.positions[symbol].qty if symbol in state.positions else 0
        return clean({
            "symbol": symbol, "side": side, "qty": qty, "price": price, "trade_date": used_date,
            "price_source": self.market.source(symbol), "gross": gross,
            "fees": fees["items"], "fees_total": fees["total"], "fees_verified": schedule.verified,
            "net_cash": -(gross + fees["total"]) if side == "BUY" else gross - fees["total"],
            "cash_available": money(state.cash), "held_qty": held, "error": error,
        })

    def post_trade(self, side: str, symbol: str, qty: int, trade_date: str | None, note: str,
                   client_order_id: str | None) -> dict:
        symbol = symbol.upper()
        insx = self.market.instrument(symbol)
        if insx is None or insx["type"] != "stock":
            raise NotFound(f"unknown stock {symbol}")
        with self.store.transaction():
            coll = self._ledger_coll()
            txs = self.store.list(coll)
            if client_order_id:
                for tx in txs:
                    if tx.get("client_order_id") == client_order_id:
                        return tx  # idempotent retry: already posted
            price, used_date = self._price_on(symbol, trade_date)
            dated = [t["trade_date"] for t in txs if t.get("trade_date")]
            if dated and used_date < max(dated):
                raise LedgerError(f"trade date {used_date} is before the last recorded trade ({max(dated)}); the ledger is chronological")
            tx = build_trade(replay(txs), self.fee_schedule(), side=side, symbol=symbol, qty=qty, price=price)
            tx.update(ts=now_iso(), trade_date=used_date, price_source=self.market.source(symbol),
                      note=note.strip(), origin="manual", mode="paper", client_order_id=client_order_id)
            saved = self.store.append(coll, tx)
            self.audit("post", "paper_trade", {"seq": saved["seq"], "side": side, "symbol": symbol, "qty": qty,
                                              "price": tx["price"], "trade_date": used_date})
            return saved

    def trades(self) -> dict:
        state = replay(self.store.list(self._ledger_coll()))
        rows = []
        for r in state.rows:
            rows.append(clean({
                **{k: r.get(k) for k in ("seq", "ts", "type", "symbol", "qty", "trade_date", "note", "price_source",
                                         "fees_verified", "remaining_qty")},
                "price": D(r["price"]) if "price" in r else None,
                "gross": D(r["gross"]) if "gross" in r else D(r.get("amount", 0)),
                "fees": [{**i, "amount": D(i["amount"])} for i in r.get("fees", [])],
                "fees_total": D(r.get("fees_total", 0)),
                "cash_delta": money(r["cash_delta"]),
                "cash_after": r["cash_after"],
                "avg_cost": money(r["avg_cost"]) if "avg_cost" in r else None,
                "realized_gross": r.get("realized_gross"),
                "buy_fees_allocated": r.get("buy_fees_allocated"),
                "realized_net": r.get("realized_net"),
            }))
        return {
            "transactions": rows[::-1],
            "totals": clean({
                "buys_gross": money(state.buys_gross), "sells_gross": money(state.sells_gross),
                "fees_paid": money(state.fees_paid), "realized_gross": money(state.realized_gross),
                "realized_net": money(state.realized_net), "count": sum(1 for r in rows if r["type"] != "DEPOSIT"),
            }),
        }

    def portfolio(self) -> dict:
        txs = self.store.list(self._ledger_coll())
        state = replay(txs)
        schedule = self.fee_schedule()
        sector_of = {i["symbol"]: i for i in self.market.instruments()}
        holdings, by_sector = [], {}
        mv_total = unreal_gross = unreal_net = est_exit = ZERO
        for pos in state.positions.values():
            if pos.qty == 0:
                continue
            price, as_of = self._price_on(pos.symbol, None)
            value = money(price * pos.qty)
            sell_fee = compute_fees(schedule, "sell", value)["total"]
            gross = value - pos.cost
            net = gross - pos.buy_fees - sell_fee
            mv_total += value
            unreal_gross += gross
            unreal_net += net
            est_exit += sell_fee
            sector = sector_of.get(pos.symbol, {}).get("sector", "Unknown")
            by_sector[sector] = by_sector.get(sector, ZERO) + value
            holdings.append({
                "symbol": pos.symbol, "name": sector_of.get(pos.symbol, {}).get("name"), "sector": sector,
                "qty": pos.qty, "avg_price": money(pos.avg_price), "last": price, "as_of": as_of,
                "source": self.market.source(pos.symbol),
                "cost": money(pos.cost), "market_value": value, "buy_fees": money(pos.buy_fees),
                "est_sell_fees": sell_fee, "unrealized_gross": money(gross), "unrealized_net_est": money(net),
                "unrealized_gross_pct": gross / pos.cost * 100 if pos.cost else None,
            })
        value_total = state.cash + mv_total
        for h in holdings:
            h["weight_pct"] = h["market_value"] / value_total * 100 if value_total else None
        net_total = state.realized_net + unreal_net
        max_stock = max((h["weight_pct"] for h in holdings), default=ZERO)
        max_sector = max((v / value_total * 100 for v in by_sector.values()), default=ZERO) if value_total else ZERO
        warnings = []
        if max_stock > 25:
            warnings.append(f"Single-stock concentration: one holding is {max_stock:.1f}% of the portfolio.")
        if max_sector > 40:
            warnings.append(f"Sector concentration: one sector is {max_sector:.1f}% of the portfolio.")
        return clean({
            "portfolio": self.store.get("portfolios", self.app_settings()["active_portfolio_id"]),
            "mode": "paper",
            "summary": {
                "starting_capital": money(state.deposits), "cash": money(state.cash),
                "invested_cost": money(sum((h["cost"] for h in holdings), ZERO)),
                "market_value": money(mv_total), "total_value": money(value_total),
                "realized_gross": money(state.realized_gross), "realized_net": money(state.realized_net),
                "unrealized_gross": money(unreal_gross), "unrealized_net_est": money(unreal_net),
                "fees_paid": money(state.fees_paid), "est_exit_fees": money(est_exit),
                "total_gross": money(state.realized_gross + unreal_gross),
                "total_net": money(net_total),
                "return_gross_pct": (state.realized_gross + unreal_gross) / state.deposits * 100 if state.deposits else None,
                "return_net_pct": net_total / state.deposits * 100 if state.deposits else None,
                "fees_verified": schedule.verified,
            },
            "holdings": sorted(holdings, key=lambda h: -h["market_value"]),
            "sector_allocation": sorted(
                ({"sector": s, "market_value": money(v), "weight_pct": v / value_total * 100} for s, v in by_sector.items()),
                key=lambda r: -r["market_value"]),
            "cash_weight_pct": state.cash / value_total * 100 if value_total else None,
            "warnings": warnings,
            "history": self._portfolio_history(txs),
        })

    def _portfolio_history(self, txs: list[dict]) -> dict:
        dated = [t for t in txs if t.get("trade_date")]
        if not dated:
            return {"curve": [], "benchmark": None}
        symbols = sorted({t["symbol"] for t in dated})
        closes = self.market.closes(symbols)
        closes = closes[closes.index >= pd.Timestamp(dated[0]["trade_date"])].ffill()
        deposits = [t for t in txs if t["type"] == "DEPOSIT"]
        curve, i = [], 0
        applied = list(deposits)
        for ts, row in closes.iterrows():
            day = ts.strftime("%Y-%m-%d")
            while i < len(dated) and dated[i]["trade_date"] <= day:
                applied.append(dated[i])
                i += 1
            st = replay(applied)
            value = st.cash + sum((D(float(row[p.symbol])) * p.qty for p in st.positions.values() if p.qty), ZERO)
            curve.append({"date": day, "value": f(value)})
        bench = None
        bsym = self.app_settings()["benchmark"]
        bdf = self.market.bars(bsym)
        if bdf is not None and curve:
            b = bdf["close"].reindex(closes.index).ffill().dropna()
            if len(b) >= 2:
                base = curve[0]["value"]
                bench = {"symbol": bsym, "source": self.market.source(bsym),
                         "curve": [{"date": d.strftime("%Y-%m-%d"), "value": round(float(v / b.iloc[0]) * base, 2)} for d, v in b.items()]}
        return {"curve": curve, "benchmark": bench}

    # ---- strategies & backtests -----------------------------------------
    def save_strategy(self, cfg: StrategyConfig, id: str | None = None) -> dict:
        known = {i["symbol"] for i in self.market.instruments()}
        unknown = [s for s in cfg.symbols if s not in known]
        if unknown:
            raise NotFound(f"unknown symbol(s): {', '.join(unknown)}")
        with self.store.transaction():
            before = self.store.get("strategies", id) if id else None
            if id and before is None:
                raise NotFound("strategy not found")
            doc = {**cfg.model_dump(mode="json"), "id": id or uuid.uuid4().hex[:12],
                   "created_at": before["created_at"] if before else now_iso(), "updated_at": now_iso()}
            self.store.put("strategies", doc["id"], doc)
            self.audit("update" if before else "create", "strategy", {"before": before, "after": doc})
            return doc

    def delete_strategy(self, id: str) -> None:
        with self.store.transaction():
            before = self.store.get("strategies", id)
            if before is None:
                raise NotFound("strategy not found")
            self.store.delete("strategies", id)
            self.audit("delete", "strategy", {"before": before})

    def strategy_universe(self, cfg: StrategyConfig, override: list[str] | None = None) -> list[str]:
        stocks = self.market.instruments()
        if override:
            wanted = {s.upper() for s in override}
            return sorted(i["symbol"] for i in stocks if i["symbol"] in wanted)
        if cfg.symbols or cfg.sectors:
            return sorted(i["symbol"] for i in stocks if i["symbol"] in cfg.symbols or i["sector"] in cfg.sectors)
        return sorted(i["symbol"] for i in stocks)

    def backtest(self, cfg: StrategyConfig, *, strategy_id: str | None, symbols: list[str] | None,
                 start: str | None, end: str | None, capital: Decimal | None) -> dict:
        universe = self.strategy_universe(cfg, symbols)
        frames = {s: df for s in universe if (df := self.market.bars(s)) is not None and len(df) > 1}
        bsym = self.app_settings()["benchmark"]
        bdf = self.market.bars(bsym)
        schedule = self.fee_schedule()
        result = run_backtest(
            cfg, frames, schedule, start=start, end=end,
            capital=capital if capital is not None else D(self.app_settings()["starting_capital"]),
            benchmark=bdf["close"] if bdf is not None else None, benchmark_name=bsym,
        )
        sources = sorted({self.market.source(s) for s in result["symbols"]})
        if "sample" in sources:
            result["warnings"].insert(0, "Run on SAMPLE (synthetic) prices: results say nothing about real EGX stocks.")
        doc = clean({
            "id": uuid.uuid4().hex[:12], "ts": now_iso(), "strategy_id": strategy_id,
            "strategy": cfg.model_dump(mode="json"), "fee_schedule": schedule.model_dump(mode="json"),
            "data_sources": sources, "mode": "backtest", **result,
        })
        with self.store.transaction():
            self.store.put("backtests", doc["id"], doc)
            self.audit("run", "backtest", {"id": doc["id"], "strategy": cfg.name, "symbols": len(result["symbols"]),
                                           "period": result["period"], "net_profit": doc["metrics"]["net_profit"]})
        return doc

    def backtests(self) -> list[dict]:
        docs = sorted(self.store.list("backtests"), key=lambda d: d["ts"], reverse=True)
        return [{k: d[k] for k in ("id", "ts", "strategy_id", "period", "symbols", "metrics", "data_sources", "warnings")}
                | {"strategy_name": d["strategy"]["name"], "strategy_type": d["strategy"]["type"]} for d in docs]

    def active_signals(self) -> list[dict]:
        """Entry/exit signals on the latest bar for every saved strategy. Informational only."""
        out = []
        for doc in self.store.list("strategies"):
            cfg = StrategyConfig.model_validate({k: doc[k] for k in StrategyConfig.model_fields})
            for symbol in self.strategy_universe(cfg):
                df = self.market.bars(symbol)
                if df is None or len(df) < 30:
                    continue
                last = signals(cfg, df).iloc[-1]
                if last["entry"] or last["exit"]:
                    out.append({"strategy_id": doc["id"], "strategy": doc["name"], "symbol": symbol,
                                "signal": "entry" if last["entry"] else "exit",
                                "date": df.index[-1].strftime("%Y-%m-%d"), "close": float(df["close"].iloc[-1]),
                                "source": self.market.source(symbol)})
        return out
