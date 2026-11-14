from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0")


def D(value) -> Decimal:
    """Exact decimal from str/int/float/Decimal (floats go through str to avoid binary noise)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def f(value) -> float:
    """Presentation-only conversion for JSON responses."""
    return float(money(value))
