from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.domain import indicators as ind
from app.domain.backtest import run_backtest
from app.domain.fees import FeeItem, FeeSchedule, compute_fees
from app.domain.ledger import LedgerError, build_trade, replay
from app.domain.strategies import StrategyConfig, signals

SCHED = FeeSchedule(items=[
    FeeItem(code="brokerage", name="Brokerage", rate_pct=Decimal("0.2"), minimum=Decimal("5")),
    FeeItem(code="other", name="Other", fixed=Decimal("3"), applies_to="buy"),
])
NO_FEES = FeeSchedule(items=[], verified=True)


def test_fees_rate_minimum_and_side():
    buy = compute_fees(SCHED, "buy", Decimal("4500"))
    assert [(i["code"], i["amount"]) for i in buy["items"]] == [("brokerage", Decimal("9.00")), ("other", Decimal("3.00"))]
    assert buy["total"] == Decimal("12.00")
    sell = compute_fees(SCHED, "sell", Decimal("1000"))  # 0.2% = 2.00 -> minimum 5
    assert sell["total"] == Decimal("5.00")


def test_fee_maximum_and_disabled():
    s = FeeSchedule(items=[
        FeeItem(code="a", name="A", rate_pct=Decimal("1"), maximum=Decimal("10")),
        FeeItem(code="b", name="B", rate_pct=Decimal("1"), enabled=False),
    ])
    assert compute_fees(s, "buy", 5000)["total"] == Decimal("10.00")


def test_duplicate_fee_codes_rejected():
    with pytest.raises(ValueError):
        FeeSchedule(items=[FeeItem(code="a", name="A"), FeeItem(code="a", name="B")])


def _post(txs, side, symbol, qty, price):
    tx = build_trade(replay(txs), SCHED, side=side, symbol=symbol, qty=qty, price=price)
    txs.append(tx)
    return tx


def test_ledger_gross_vs_net_and_partial_sale():
    txs = [{"type": "DEPOSIT", "amount": "50000"}]
    _post(txs, "BUY", "CANA", 100, "45")      # gross 4500, fees 9 + 3 = 12
    _post(txs, "BUY", "CANA", 100, "55")      # gross 5500, fees 11 + 3 = 14
    st = replay(txs)
    assert st.cash == Decimal("50000") - Decimal("4512") - Decimal("5514")
    assert st.positions["CANA"].avg_price == Decimal("50")
    _post(txs, "SELL", "CANA", 50, "60")      # gross 3000, sell fee 6
    st = replay(txs)
    row = st.rows[-1]
    assert row["realized_gross"] == Decimal("500.00")          # (60 - 50) * 50
    assert row["buy_fees_allocated"] == Decimal("6.50")        # 26 * 50/200
    assert row["realized_net"] == Decimal("487.50")            # 500 - 6.50 - 6
    assert row["remaining_qty"] == 150
    assert st.positions["CANA"].avg_price == Decimal("50")
    assert st.positions["CANA"].buy_fees == Decimal("19.5")
    # cash identity: deposits - buys - buy fees + sells - sell fees
    assert st.cash == Decimal("50000") - 10000 - 26 + 3000 - 6
    assert st.fees_paid == Decimal("32")


def test_ledger_full_exit_net_equals_cash_change():
    txs = [{"type": "DEPOSIT", "amount": "10000"}]
    _post(txs, "BUY", "COMI", 20, "80")
    _post(txs, "SELL", "COMI", 20, "90")
    st = replay(txs)
    assert st.positions["COMI"].qty == 0
    assert st.realized_net == st.cash - Decimal("10000")
    assert st.realized_gross == Decimal("200")


def test_ledger_rejects_overdraft_and_oversell():
    txs = [{"type": "DEPOSIT", "amount": "1000"}]
    with pytest.raises(LedgerError, match="insufficient cash"):
        _post(txs, "BUY", "COMI", 10, "100")  # 1000 gross + fees > 1000 cash
    with pytest.raises(LedgerError, match="only 0 held"):
        _post(txs, "SELL", "COMI", 1, "100")
    with pytest.raises(LedgerError):
        _post(txs, "BUY", "COMI", 0, "100")


def _frame(closes, volume=1000.0):
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c * 1.01, "low": c * 0.99, "close": c, "volume": volume})


def test_rsi_bounds_and_extremes():
    up = ind.rsi(pd.Series(np.arange(1.0, 40.0)))
    assert up.iloc[-1] == 100
    down = ind.rsi(pd.Series(np.arange(40.0, 1.0, -1)))
    assert down.iloc[-1] == pytest.approx(0)
    assert up.iloc[:14].isna().all()


def test_sma_and_resample():
    df = _frame(list(range(1, 31)))
    assert ind.sma(df["close"], 5).iloc[-1] == pytest.approx(28)
    weekly = ind.resample(df, "w")
    assert weekly["volume"].sum() == df["volume"].sum()
    assert weekly["close"].iloc[-1] == df["close"].iloc[-1]


def test_strategy_validation():
    with pytest.raises(ValueError, match="shorter"):
        StrategyConfig(name="x", type="sma_cross", params={"fast": 50, "slow": 20})
    with pytest.raises(ValueError, match="fundamental|financial"):
        StrategyConfig(name="x", type="fundamental_value")
    with pytest.raises(ValueError, match="unknown parameter"):
        StrategyConfig(name="x", type="sma_cross", params={"bogus": 1})
    assert StrategyConfig(name="x", type="sma_cross").params == {"fast": 20.0, "slow": 50.0}


def test_signals_have_no_lookahead():
    rng = np.random.default_rng(1)
    df = _frame(list(50 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))))
    for kind in ("sma_cross", "rsi_reversion", "macd_cross", "breakout"):
        cfg = StrategyConfig(name=kind, type=kind)
        full = signals(cfg, df)
        cut = signals(cfg, df.iloc[:200])
        pd.testing.assert_frame_equal(full.iloc[:200], cut)


def test_backtest_fills_next_open_and_accounts_for_fees():
    closes = [10.0] * 60 + [10 + i * 0.5 for i in range(1, 41)] + [30 - i for i in range(1, 21)]
    df = _frame(closes)
    cfg = StrategyConfig(name="t", type="sma_cross", params={"fast": 5, "slow": 20},
                         risk={"stop_loss_pct": None, "max_alloc_pct": 100, "cash_reserve_pct": 0, "slippage_bps": 0})
    res = run_backtest(cfg, {"AAA": df}, SCHED, start=None, end=None, capital=10000)
    assert res["metrics"]["trades"] == 1
    t = res["trades"][0]
    sig = signals(cfg, df)
    entry_bar = sig.index[sig["entry"]][0]
    fill_bar = df.index[df.index.get_loc(entry_bar) + 1]
    assert t["entry_date"] == fill_bar.strftime("%Y-%m-%d")
    assert t["entry_price"] == pytest.approx(df.loc[fill_bar, "open"])
    m = res["metrics"]
    assert m["net_profit"] == pytest.approx(m["gross_profit"] - m["total_fees"] - m["est_exit_fees_open_positions"])
    assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["fees"])
    assert m["final_equity"] == pytest.approx(10000 + t["net_pnl"])
    assert m["net_profit"] < m["gross_profit"]
    assert res["equity_curve"][0]["equity"] == 10000
    assert any("Only 1 closed trade" in w for w in res["warnings"])


def test_backtest_stop_loss_and_no_fees_identity():
    closes = [10.0] * 30 + [11, 12, 13, 14, 15, 16, 17, 18, 9, 9, 9, 9, 9, 9, 9, 9]
    df = _frame(closes)
    cfg = StrategyConfig(name="t", type="sma_cross", params={"fast": 2, "slow": 5},
                         risk={"stop_loss_pct": 10, "max_alloc_pct": 50, "cash_reserve_pct": 0, "slippage_bps": 0})
    res = run_backtest(cfg, {"AAA": df}, NO_FEES, start=None, end=None, capital=10000)
    assert res["trades"][0]["exit_reason"] == "stop_loss"
    assert res["metrics"]["total_fees"] == 0
    assert res["metrics"]["net_profit"] == pytest.approx(res["metrics"]["gross_profit"])
    assert res["metrics"]["max_drawdown_pct"] < 0
