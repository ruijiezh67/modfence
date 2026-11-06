"""Formula AST."""

from dataclasses import dataclass

from sheet.cells.address import CellAddress
from sheet.cells.ranges import CellRange


@dataclass(frozen=True)
class Number:
    """A numeric literal."""

    value: float


@dataclass(frozen=True)
class Ref:
    """A reference to one cell."""

    address: CellAddress


@dataclass(frozen=True)
class RangeRef:
    """A reference to a rectangular range."""

    cells: CellRange


@dataclass(frozen=True)
class Neg:
    """Unary minus."""

    operand: "Node"


@dataclass(frozen=True)
class BinOp:
    """A binary arithmetic operation."""

    op: str
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Call:
    """A function call such as ``SUM(A1:A3)``."""

    name: str
    args: tuple["Node", ...]


Node = Number | Ref | RangeRef | Neg | BinOp | Call
