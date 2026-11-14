"""Configurable fee schedule.

Nothing here is a statement of the broker's real tariff. The defaults are
placeholders flagged `verified: false`; the user must check them against the
broker's current tariff and mark the schedule verified in Settings.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .money import ZERO, D, money

Side = Literal["buy", "sell"]


class FeeItem(BaseModel):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=80)
    rate_pct: Decimal = Field(default=ZERO, ge=0, le=10)  # percent of gross trade value
    fixed: Decimal = Field(default=ZERO, ge=0)  # flat EGP amount per trade
    minimum: Decimal = Field(default=ZERO, ge=0)
    maximum: Decimal | None = Field(default=None, ge=0)
    applies_to: Literal["buy", "sell", "both"] = "both"
    enabled: bool = True


class FeeSchedule(BaseModel):
    items: list[FeeItem]
    verified: bool = False
    note: str = ""

    @field_validator("items")
    @classmethod
    def unique_codes(cls, items: list[FeeItem]) -> list[FeeItem]:
        codes = [i.code for i in items]
        if len(codes) != len(set(codes)):
            raise ValueError("fee item codes must be unique")
        return items


DEFAULT_FEE_SCHEDULE = FeeSchedule(
    verified=False,
    note=(
        "Placeholder assumptions only. Verify every line against your broker's "
        "current tariff before relying on net-profit figures."
    ),
    items=[
        FeeItem(code="brokerage", name="Brokerage commission", rate_pct=Decimal("0.15"), minimum=Decimal("3")),
        FeeItem(code="exchange", name="Exchange (EGX) fee", rate_pct=Decimal("0.012")),
        FeeItem(code="clearing", name="Clearing and settlement (MCDR)", rate_pct=Decimal("0.0125")),
        FeeItem(code="regulatory", name="Regulatory (FRA) charge", rate_pct=Decimal("0.005")),
        FeeItem(code="stamp_duty", name="Stamp duty / tax", rate_pct=Decimal("0.125")),
        FeeItem(code="other", name="Other charges", enabled=False),
    ],
)


def compute_fees(schedule: FeeSchedule, side: Side, gross) -> dict:
    """Return {'items': [{code,name,amount}], 'total': Decimal} for one trade."""
    gross = D(gross)
    lines = []
    total = ZERO
    for item in schedule.items:
        if not item.enabled or item.applies_to not in (side, "both"):
            continue
        amount = gross * item.rate_pct / Decimal(100) + item.fixed
        if amount < item.minimum:
            amount = item.minimum
        if item.maximum is not None and amount > item.maximum:
            amount = item.maximum
        amount = money(amount)
        if amount == ZERO:
            continue
        lines.append({"code": item.code, "name": item.name, "amount": amount})
        total += amount
    return {"items": lines, "total": money(total)}
