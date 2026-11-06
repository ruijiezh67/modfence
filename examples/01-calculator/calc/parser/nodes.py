"""AST node types."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Num:
    """A numeric literal."""

    value: int | float


@dataclass(frozen=True)
class UnaryOp:
    """A prefix operator applied to one operand."""

    op: str
    operand: "Node"


@dataclass(frozen=True)
class BinOp:
    """An infix operator applied to two operands."""

    op: str
    left: "Node"
    right: "Node"


Node = Num | UnaryOp | BinOp
