"""Rectangular cell ranges such as ``A1:B3``."""

from dataclasses import dataclass

from sheet.cells.address import CellAddress, InvalidAddress, parse_address


@dataclass(frozen=True)
class CellRange:
    """A normalized rectangle: ``start`` is top-left, ``end`` is bottom-right."""

    start: CellAddress
    end: CellAddress

    def addresses(self) -> list[CellAddress]:
        """All cells in the range, row by row."""
        return [
            CellAddress(row, col)
            for row in range(self.start.row, self.end.row + 1)
            for col in range(self.start.col, self.end.col + 1)
        ]

    @property
    def label(self) -> str:
        """The spreadsheet name, e.g. ``A1:B3``."""
        return f"{self.start.label}:{self.end.label}"


def make_range(a: CellAddress, b: CellAddress) -> CellRange:
    """Build a range from any two opposite corners."""
    return CellRange(
        CellAddress(min(a.row, b.row), min(a.col, b.col)),
        CellAddress(max(a.row, b.row), max(a.col, b.col)),
    )


def parse_range(text: str) -> CellRange:
    """Parse ``"A1:B3"``; a single cell like ``"A1"`` is not a range."""
    parts = text.split(":")
    if len(parts) != 2:
        raise InvalidAddress(f"not a range: {text!r}")
    return make_range(parse_address(parts[0]), parse_address(parts[1]))
