"""Cell values and error values."""

from enum import Enum


class CellError(str, Enum):
    """Error values a cell can hold."""

    CYCLE = "#CYCLE!"
    REF = "#REF!"
    DIV0 = "#DIV/0!"
    NAME = "#NAME?"
    SYNTAX = "#ERR!"


Value = float | CellError


def format_value(value: Value | None) -> str:
    """Display text of a value: ``3.0`` -> ``3``, empty -> empty string."""
    if value is None:
        return ""
    if isinstance(value, CellError):
        return value.value
    return str(int(value)) if value.is_integer() else f"{value:.10g}"
