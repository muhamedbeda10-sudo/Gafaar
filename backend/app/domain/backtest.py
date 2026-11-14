"""Historical backtester (daily bars, long-only, whole shares).

Execution model
* Signals are computed at the close of day T and filled at the OPEN of T+1.
* Buys pay open x (1 + slippage); sells receive price x (1 - slippage).
* Stop-loss / take-profit are checked against each day's low / high. A gap
  through the level fills at the open. If both are touched in one bar the stop
  is assumed to have come first (conservative).
* Every fill is charged the configured fee schedule, exactly like the ledger.
* The backtester never sends orders anywhere. It only reads historical bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from .fees import FeeSchedule, compute_fees
from .money import ZERO, D, money
from .strategies import StrategyConfig, signals

MIN_TRADES_FOR_CONFIDENCE = 30


class BacktestError(ValueError):
    pass


@dataclass
class _Open:
    symbol: str
    qty: int
    entry_date: str
    entry_price: Decimal
    buy_gross: Decimal
    buy_fees: Decimal


def run_backtest(
    cfg: StrategyConfig,
    frames: dict[str, pd.DataFrame],
    schedule: FeeSchedule,
    *,
    start: str | None,
    end: str | None,
    capital,
    benchmark: pd.Series | None = None,
    benchmark_name: str | None = None,
) -> dict:
    capital = money(capital)
    if capital <= 0:
        raise BacktestError("starting capital must be positive")
    if not frames:
        raise BacktestError("no price history for the selected stocks")
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    if start_ts is not None and end_ts is not None and start_ts >= end_ts:
        raise BacktestError("start date must be before end date")

    # Signals use the full history (warm-up) but trading is confined to [start, end].
    sig = {s: signals(cfg, df) for s, df in frames.items()}
    window: dict[str, pd.DataFrame] = {}
    for s, df in frames.items():
        w = df
        if start_ts is not None:
            w = w[w.index >= start_ts]
        if end_ts is not None:
            w = w[w.index <= end_ts]
        if len(w):
            window[s] = w
    if not window:
        raise BacktestError("no price data inside the selected period")
    dates = sorted(set().union(*(w.index for w in window.values())))
    if len(dates) < 2:
        raise BacktestError("the selected period has fewer than 2 sessions")

    risk = cfg.risk
    slip = D(risk.slippage_bps) / Decimal(10000)
    cash = capital
    open_pos: dict[str, _Open] = {}
    pending_buy: list[str] = []
    pending_sell: set[str] = set()
    last_close: dict[str, Decimal] = {}
    trades: list[dict] = []
    curve: list[dict] = []
    fees_total = ZERO
    days_invested = 0

    def equity() -> Decimal:
        return cash + sum((last_close[p.symbol] * p.qty for p in open_pos.values()), ZERO)

    def close_position(pos: _Open, date, raw_price: Decimal, reason: str) -> None:
        nonlocal cash, fees_total
        price = money(raw_price * (1 - slip))
        gross = money(price * pos.qty)
        fee = compute_fees(schedule, "sell", gross)["total"]
        cash += gross - fee
        fees_total += fee
        gross_pnl = gross - pos.buy_gross
        trades.append({
            "symbol": pos.symbol,
            "qty": pos.qty,
            "entry_date": pos.entry_date,
            "entry_price": float(pos.entry_price),
            "exit_date": date.strftime("%Y-%m-%d"),
            "exit_price": float(price),
            "exit_reason": reason,
            "gross_pnl": float(gross_pnl),
            "fees": float(pos.buy_fees + fee),
            "net_pnl": float(gross_pnl - pos.buy_fees - fee),
            "return_pct": float((gross_pnl - pos.buy_fees - fee) / (pos.buy_gross + pos.buy_fees) * 100),
        })
        del open_pos[pos.symbol]

    for date in dates:
        today = {s: w.loc[date] for s, w in window.items() if date in w.index}

        # 1) fill orders decided at the previous close
        for s in sorted(pending_sell):
            if s in open_pos and s in today:
                close_position(open_pos[s], date, D(today[s]["open"]), "signal")
        pending_sell = {s for s in pending_sell if s in open_pos}  # no bar today: retry next session
        eq = equity()
        reserve = eq * D(risk.cash_reserve_pct) / 100
        still_pending: list[str] = []
        for s in pending_buy:
            if s in open_pos:
                continue
            if s not in today:
                still_pending.append(s)
                continue
            if len(open_pos) >= risk.max_open_positions:
                continue
            price = money(D(today[s]["open"]) * (1 + slip))
            budget = min(eq * D(risk.max_alloc_pct) / 100, cash - reserve)
            qty = int(budget // price) if price > 0 else 0
            while qty > 0:
                gross = money(price * qty)
                fee = compute_fees(schedule, "buy", gross)["total"]
                if gross + fee <= budget:
                    break
                qty -= 1
            if qty <= 0:
                continue
            cash -= gross + fee
            fees_total += fee
            open_pos[s] = _Open(s, qty, date.strftime("%Y-%m-%d"), price, gross, fee)
            last_close[s] = price
        pending_buy = still_pending

        # 2) protective exits inside the session
        for s, pos in list(open_pos.items()):
            if s not in today:
                continue
            bar = today[s]
            o, hi, lo = D(bar["open"]), D(bar["high"]), D(bar["low"])
            if risk.stop_loss_pct is not None:
                stop = pos.entry_price * (1 - D(risk.stop_loss_pct) / 100)
                if lo <= stop:
                    close_position(pos, date, min(o, stop), "stop_loss")
                    continue
            if risk.take_profit_pct is not None:
                target = pos.entry_price * (1 + D(risk.take_profit_pct) / 100)
                if hi >= target:
                    close_position(pos, date, max(o, target), "take_profit")

        # 3) mark to market and read signals at the close
        for s, bar in today.items():
            last_close[s] = D(bar["close"])
            row = sig[s].loc[date]
            if s in open_pos:
                if row["exit"]:
                    pending_sell.add(s)
            elif row["entry"] and s not in pending_buy:
                pending_buy.append(s)
        if open_pos:
            days_invested += 1
        curve.append({"date": date.strftime("%Y-%m-%d"), "equity": float(money(equity()))})

    # ---- results ---------------------------------------------------------
    open_positions = []
    est_exit_fees = ZERO
    for pos in open_pos.values():
        mark = last_close[pos.symbol]
        value = money(mark * pos.qty)
        fee = compute_fees(schedule, "sell", value)["total"]
        est_exit_fees += fee
        open_positions.append({
            "symbol": pos.symbol, "qty": pos.qty, "entry_date": pos.entry_date,
            "entry_price": float(pos.entry_price), "last_price": float(mark),
            "gross_unrealized": float(value - pos.buy_gross),
            "net_unrealized_est": float(value - pos.buy_gross - pos.buy_fees - fee),
        })
    final_equity = money(equity())
    liquidation = final_equity - est_exit_fees
    net_profit = liquidation - capital
    gross_profit = net_profit + fees_total + est_exit_fees

    eq_series = pd.Series([c["equity"] for c in curve])
    drawdown = (eq_series / eq_series.cummax() - 1) * 100
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_sum = sum(t["net_pnl"] for t in wins)
    loss_sum = -sum(t["net_pnl"] for t in losses)

    bench = None
    idx = pd.DatetimeIndex(dates)
    if benchmark is not None:
        b = benchmark.reindex(idx).ffill().dropna()
        if len(b) >= 2:
            norm = b / b.iloc[0] * float(capital)
            bench = {
                "name": benchmark_name,
                "return_pct": float(b.iloc[-1] / b.iloc[0] - 1) * 100,
                "curve": [{"date": d.strftime("%Y-%m-%d"), "equity": round(float(v), 2)} for d, v in norm.items()],
            }
    closes = pd.DataFrame({s: w["close"] for s, w in window.items()}).reindex(idx).ffill()
    hold = (closes / closes.bfill().iloc[0]).mean(axis=1)
    buy_hold = {
        "name": "Equal-weight buy & hold of the tested stocks (before fees)",
        "return_pct": float(hold.iloc[-1] - 1) * 100,
        "curve": [{"date": d.strftime("%Y-%m-%d"), "equity": round(float(v) * float(capital), 2)} for d, v in hold.items()],
    }

    warnings = []
    if len(trades) < MIN_TRADES_FOR_CONFIDENCE:
        warnings.append(
            f"Only {len(trades)} closed trade(s): the sample is too small to judge this strategy "
            f"(aim for {MIN_TRADES_FOR_CONFIDENCE}+)."
        )
    if not schedule.verified:
        warnings.append("Fee schedule is not verified against the broker tariff; net figures are estimates.")

    return {
        "period": {"start": curve[0]["date"], "end": curve[-1]["date"], "sessions": len(curve)},
        "symbols": sorted(window),
        "metrics": {
            "starting_capital": float(capital),
            "final_equity": float(final_equity),
            "liquidation_value": float(liquidation),
            "gross_profit": float(gross_profit),
            "total_fees": float(fees_total),
            "est_exit_fees_open_positions": float(est_exit_fees),
            "net_profit": float(net_profit),
            "total_return_pct": float(net_profit / capital * 100),
            "gross_return_pct": float(gross_profit / capital * 100),
            "max_drawdown_pct": float(drawdown.min()),
            "trades": len(trades),
            "win_rate_pct": len(wins) / len(trades) * 100 if trades else None,
            "avg_net_per_trade": sum(t["net_pnl"] for t in trades) / len(trades) if trades else None,
            "profit_factor": win_sum / loss_sum if loss_sum > 0 else None,
            "best_trade": max(trades, key=lambda t: t["net_pnl"]) if trades else None,
            "worst_trade": min(trades, key=lambda t: t["net_pnl"]) if trades else None,
            "exposure_pct": days_invested / len(curve) * 100,
        },
        "equity_curve": curve,
        "benchmark": bench,
        "buy_and_hold": buy_hold,
        "trades": trades,
        "open_positions": open_positions,
        "warnings": warnings,
    }
