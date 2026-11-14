"""Paper-trading ledger.

The ledger is append-only. Cash, positions and every profit figure are derived
by replaying it, so there is exactly one implementation of the accounting rules:

* average cost per share excludes fees (fees are tracked separately),
* gross profit  = (sell price - average cost) x quantity,
* net realized  = gross profit - proportional buy fees - sell fees,
* unrealized net is an estimate: it subtracts the remaining buy fees and the
  sell fees that would be charged if the position were closed at the last price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .fees import FeeSchedule, compute_fees
from .money import ZERO, D, money


class LedgerError(ValueError):
    pass


@dataclass
class Position:
    symbol: str
    qty: int = 0
    cost: Decimal = ZERO  # gross cost of remaining shares, excluding fees
    buy_fees: Decimal = ZERO  # buy fees attributable to remaining shares

    @property
    def avg_price(self) -> Decimal:
        return self.cost / self.qty if self.qty else ZERO


@dataclass
class LedgerState:
    cash: Decimal = ZERO
    deposits: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    realized_gross: Decimal = ZERO
    realized_net: Decimal = ZERO
    fees_paid: Decimal = ZERO
    buys_gross: Decimal = ZERO
    sells_gross: Decimal = ZERO
    rows: list[dict] = field(default_factory=list)  # transactions enriched with derived figures


def replay(transactions: list[dict]) -> LedgerState:
    st = LedgerState()
    for tx in transactions:
        row = dict(tx)
        kind = tx["type"]
        if kind == "DEPOSIT":
            amount = D(tx["amount"])
            st.cash += amount
            st.deposits += amount
            row["cash_delta"] = amount
        elif kind in ("BUY", "SELL"):
            qty = int(tx["qty"])
            gross = D(tx["gross"])
            fees = D(tx["fees_total"])
            pos = st.positions.setdefault(tx["symbol"], Position(tx["symbol"]))
            st.fees_paid += fees
            if kind == "BUY":
                pos.qty += qty
                pos.cost += gross
                pos.buy_fees += fees
                st.cash -= gross + fees
                st.buys_gross += gross
                row["cash_delta"] = -(gross + fees)
            else:
                if qty > pos.qty:
                    raise LedgerError(f"ledger corrupt: sell of {qty} {tx['symbol']} exceeds holding {pos.qty}")
                avg = pos.avg_price
                cost_out = pos.cost * qty / pos.qty
                buy_fees_out = pos.buy_fees * qty / pos.qty
                realized_gross = gross - cost_out
                realized_net = realized_gross - buy_fees_out - fees
                pos.qty -= qty
                pos.cost -= cost_out
                pos.buy_fees -= buy_fees_out
                if pos.qty == 0:
                    pos.cost = ZERO
                    pos.buy_fees = ZERO
                st.cash += gross - fees
                st.sells_gross += gross
                st.realized_gross += realized_gross
                st.realized_net += realized_net
                row.update(
                    avg_cost=avg,
                    realized_gross=money(realized_gross),
                    buy_fees_allocated=money(buy_fees_out),
                    realized_net=money(realized_net),
                    cash_delta=gross - fees,
                )
            row["remaining_qty"] = pos.qty
        else:
            raise LedgerError(f"unknown transaction type {kind!r}")
        row["cash_after"] = money(st.cash)
        st.rows.append(row)
    return st


def build_trade(
    state: LedgerState,
    schedule: FeeSchedule,
    *,
    side: str,
    symbol: str,
    qty: int,
    price,
) -> dict:
    """Validate an order against the current state and return the transaction to append."""
    if side not in ("BUY", "SELL"):
        raise LedgerError("side must be BUY or SELL")
    if qty <= 0:
        raise LedgerError("quantity must be a positive whole number of shares")
    price = D(price)
    if price <= 0:
        raise LedgerError("price must be positive")
    gross = money(price * qty)
    fees = compute_fees(schedule, side.lower(), gross)
    if side == "BUY":
        needed = gross + fees["total"]
        if needed > state.cash:
            raise LedgerError(
                f"insufficient cash: need EGP {needed:,.2f} including fees, available EGP {money(state.cash):,.2f}"
            )
    else:
        held = state.positions.get(symbol).qty if symbol in state.positions else 0
        if qty > held:
            raise LedgerError(f"cannot sell {qty} shares of {symbol}: only {held} held")
    return {
        "type": side,
        "symbol": symbol,
        "qty": qty,
        "price": str(price),
        "gross": str(gross),
        "fees": [{**i, "amount": str(i["amount"])} for i in fees["items"]],
        "fees_total": str(fees["total"]),
        "fees_verified": schedule.verified,
    }
