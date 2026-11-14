"""EGX Intelligence API. Paper trading only: nothing in this service can send an order to a broker."""
from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .data.market import DataError
from .domain.backtest import BacktestError
from .domain.fees import FeeSchedule
from .domain.ledger import LedgerError
from .domain.strategies import STRATEGY_TYPES, StrategyConfig
from .services import App, NotFound
from .store.sqlite_store import Store

MAX_CSV_BYTES = 5 * 1024 * 1024


class TradeIn(BaseModel):
    side: Literal["BUY", "SELL"]
    symbol: str = Field(min_length=1, max_length=12)
    qty: int = Field(gt=0, le=100_000_000)
    trade_date: date | None = None
    note: str = Field(default="", max_length=1000)
    client_order_id: str | None = Field(default=None, max_length=64)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    symbols: list[str] = Field(default_factory=list, max_length=300)


class AppSettingsIn(BaseModel):
    starting_capital: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"))
    benchmark: str | None = Field(default=None, max_length=12)


class BacktestIn(BaseModel):
    strategy_id: str | None = None
    strategy: StrategyConfig | None = None
    symbols: list[str] | None = Field(default=None, max_length=300)
    start: date | None = None
    end: date | None = None
    capital: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"))


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    core = App(store or Store(settings.data_dir / "egx.sqlite3"), settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        core.bootstrap()
        yield

    api = FastAPI(title="EGX Intelligence API", version="0.1.0", lifespan=lifespan)
    api.state.core = core
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"], allow_headers=["*"],
    )

    @api.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @api.exception_handler(LedgerError)
    @api.exception_handler(DataError)
    @api.exception_handler(BacktestError)
    async def _rule_violation(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def iso(d: date | None) -> str | None:
        return d.isoformat() if d else None

    # ---- system ----------------------------------------------------------
    @api.get("/health")
    def health():
        return {"status": "ok", "environment": settings.app_env}

    @api.get("/api/v1/status")
    def status():
        return {
            "trading_mode": "paper",
            "live_trading_enabled": False,
            "broker_connected": False,
            "broker_note": "Younit is not connected. This release cannot send orders to any broker.",
            "data": core.market.status(),
            "fees_verified": core.fee_schedule().verified,
        }

    # ---- market ----------------------------------------------------------
    @api.get("/api/v1/market/overview")
    def market_overview():
        return core.market_overview()

    @api.get("/api/v1/market/sectors")
    def market_sectors():
        return core.sectors()

    @api.get("/api/v1/stocks")
    def stocks(sector: str | None = None, q: str | None = Query(default=None, max_length=60),
               category: str | None = None):
        return core.stock_rows(sector, q, category)

    @api.get("/api/v1/stocks/{symbol}")
    def stock(symbol: str, timeframe: Literal["d", "w", "m"] = "d"):
        return core.stock_detail(symbol, timeframe)

    # ---- watchlist & categories -----------------------------------------
    @api.get("/api/v1/watchlist")
    def watchlist():
        return core.watchlist()

    @api.put("/api/v1/watchlist/{symbol}")
    def watch(symbol: str):
        core.set_watch(symbol, True)
        return {"symbol": symbol.upper(), "watched": True}

    @api.delete("/api/v1/watchlist/{symbol}")
    def unwatch(symbol: str):
        core.set_watch(symbol, False)
        return {"symbol": symbol.upper(), "watched": False}

    @api.get("/api/v1/categories")
    def categories():
        return core.store.list("categories")

    @api.post("/api/v1/categories", status_code=201)
    def create_category(body: CategoryIn):
        return core.save_category(body.name, body.symbols)

    @api.put("/api/v1/categories/{id}")
    def update_category(id: str, body: CategoryIn):
        return core.save_category(body.name, body.symbols, id)

    @api.delete("/api/v1/categories/{id}")
    def delete_category(id: str):
        if not core.store.delete("categories", id):
            raise HTTPException(404, "category not found")
        core.audit("delete", "category", {"id": id})
        return {"deleted": id}

    # ---- portfolio & trades ---------------------------------------------
    @api.get("/api/v1/portfolio")
    def portfolio():
        return core.portfolio()

    @api.post("/api/v1/portfolio/reset")
    def reset_portfolio():
        return core.reset_portfolio()

    @api.get("/api/v1/trades")
    def trades():
        return core.trades()

    @api.post("/api/v1/trades/preview")
    def preview_trade(body: TradeIn):
        return core.preview_trade(body.side, body.symbol, body.qty, iso(body.trade_date))

    @api.post("/api/v1/trades", status_code=201)
    def post_trade(body: TradeIn):
        return core.post_trade(body.side, body.symbol, body.qty, iso(body.trade_date), body.note, body.client_order_id)

    @api.get("/api/v1/trades/export.csv")
    def export_trades():
        buf = io.StringIO()
        cols = ["seq", "ts", "trade_date", "type", "symbol", "qty", "price", "gross", "fees_total", "cash_delta",
                "cash_after", "avg_cost", "realized_gross", "buy_fees_allocated", "realized_net", "price_source", "note"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in reversed(core.trades()["transactions"]):
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in cols})
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="egx-paper-trades.csv"'})

    # ---- settings --------------------------------------------------------
    @api.get("/api/v1/settings")
    def get_app_settings():
        return core.app_settings()

    @api.put("/api/v1/settings")
    def put_app_settings(body: AppSettingsIn):
        return core.update_app_settings(starting_capital=body.starting_capital, benchmark=body.benchmark)

    @api.get("/api/v1/settings/fees")
    def get_fees():
        return core.fee_schedule()

    @api.put("/api/v1/settings/fees")
    def put_fees(body: FeeSchedule):
        return core.update_fee_schedule(body)

    # ---- strategies & backtests -----------------------------------------
    @api.get("/api/v1/strategy-types")
    def strategy_types():
        return STRATEGY_TYPES

    @api.get("/api/v1/strategies")
    def strategies():
        return core.store.list("strategies")

    @api.post("/api/v1/strategies", status_code=201)
    def create_strategy(body: StrategyConfig):
        return core.save_strategy(body)

    @api.put("/api/v1/strategies/{id}")
    def update_strategy(id: str, body: StrategyConfig):
        return core.save_strategy(body, id)

    @api.delete("/api/v1/strategies/{id}")
    def delete_strategy(id: str):
        core.delete_strategy(id)
        return {"deleted": id}

    @api.get("/api/v1/signals")
    def active_signals():
        return core.active_signals()

    @api.post("/api/v1/backtests", status_code=201)
    def run_backtest(body: BacktestIn):
        if body.strategy is not None:
            cfg = body.strategy
        elif body.strategy_id:
            doc = core.store.get("strategies", body.strategy_id)
            if doc is None:
                raise HTTPException(404, "strategy not found")
            cfg = StrategyConfig.model_validate({k: doc[k] for k in StrategyConfig.model_fields})
        else:
            raise HTTPException(422, "provide strategy_id or strategy")
        return core.backtest(cfg, strategy_id=body.strategy_id, symbols=body.symbols,
                             start=iso(body.start), end=iso(body.end), capital=body.capital)

    @api.get("/api/v1/backtests")
    def list_backtests():
        return core.backtests()

    @api.get("/api/v1/backtests/{id}")
    def get_backtest(id: str):
        doc = core.store.get("backtests", id)
        if doc is None:
            raise HTTPException(404, "backtest not found")
        return doc

    # ---- data import & audit --------------------------------------------
    @api.post("/api/v1/data/bars/import")
    async def import_bars(symbol: str = Form(max_length=12), file: UploadFile = File(),
                          name: str | None = Form(default=None, max_length=120),
                          sector: str | None = Form(default=None, max_length=80)):
        raw = await file.read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            raise HTTPException(413, "file too large (5 MB max)")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "file must be UTF-8 text") from None
        result = core.market.import_csv(symbol, text, name=name, sector=sector)
        core.audit("import", "bars", {**result, "filename": file.filename})
        return result

    @api.get("/api/v1/audit")
    def audit(limit: int = Query(default=100, ge=1, le=1000)):
        return core.store.list("audit")[::-1][:limit]

    return api


app = create_app()
