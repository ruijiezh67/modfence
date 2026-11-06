"""Cell addresses such as ``A1`` or ``AB12``."""

import re
from dataclasses import dataclass

MAX_COL = 702  # column ZZ
MAX_ROW = 9999

_ADDRESS = re.compile(r"([A-Za-z]+)([0-9]+)")


class InvalidAddress(ValueError):
    """Raised for malformed or out-of-bounds addresses."""


@dataclass(frozen=True, order=True)
class CellAddress:
    """A 1-based (row, col) position. Ordering is row-major."""

    row: int
    col: int

    @property
    def label(self) -> str:
        """The spreadsheet name of the cell, e.g. ``B3``."""
        return f"{column_letters(self.col)}{self.row}"


def column_letters(col: int) -> str:
    """Convert a 1-based column number to letters (1 -> A, 27 -> AA)."""
    letters = ""
    while col > 0:
        col, rest = divmod(col - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def column_index(letters: str) -> int:
    """Convert column letters to a 1-based number (A -> 1, AA -> 27)."""
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def parse_address(text: str) -> CellAddress:
    """Parse ``text`` like ``"b3"``; raise InvalidAddress if it is not a valid cell."""
    match = _ADDRESS.fullmatch(text.strip())
    if match is None:
        raise InvalidAddress(f"not a cell address: {text!r}")
    col, row = column_index(match.group(1)), int(match.group(2))
    if not (1 <= col <= MAX_COL and 1 <= row <= MAX_ROW):
        raise InvalidAddress(f"address out of bounds: {text!r}")
    return CellAddress(row, col)
