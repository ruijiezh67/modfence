"""Built-in functions. Each takes the flattened numeric arguments."""

from collections.abc import Sequence


def fn_sum(values: Sequence[float]) -> float:
    """Sum of the values (0 for none)."""
    return float(sum(values))


def fn_min(values: Sequence[float]) -> float:
    """Smallest value (0 for none)."""
    return float(min(values, default=0.0))


def fn_max(values: Sequence[float]) -> float:
    """Largest value (0 for none)."""
    return float(max(values, default=0.0))


def fn_avg(values: Sequence[float]) -> float:
    """Mean of the values; raises ZeroDivisionError for none."""
    if not values:
        raise ZeroDivisionError("AVG of no values")
    return float(sum(values)) / len(values)
