"""Evaluates a formula AST against a cell lookup."""

from collections.abc import Callable

from sheet.cells.address import CellAddress
from sheet.engine.values import CellError, Value
from sheet.formula.nodes import BinOp, Call, Neg, Node, Number, RangeRef, Ref
from sheet.functions.registry import Registry

Lookup = Callable[[CellAddress], Value | None]


def evaluate(node: Node, lookup: Lookup, registry: Registry) -> Value:
    """Compute the value of ``node``. Errors propagate as CellError values."""
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Ref):
        value = lookup(node.address)
        return 0.0 if value is None else value
    if isinstance(node, RangeRef):
        return CellError.SYNTAX  # a bare range is only valid inside a function call
    if isinstance(node, Neg):
        value = evaluate(node.operand, lookup, registry)
        return value if isinstance(value, CellError) else -value
    if isinstance(node, BinOp):
        return _binary(node, lookup, registry)
    return _call(node, lookup, registry)


def _binary(node: BinOp, lookup: Lookup, registry: Registry) -> Value:
    left = evaluate(node.left, lookup, registry)
    right = evaluate(node.right, lookup, registry)
    for operand in (left, right):
        if isinstance(operand, CellError):
            return operand
    if node.op == "+":
        return left + right
    if node.op == "-":
        return left - right
    if node.op == "*":
        return left * right
    return CellError.DIV0 if right == 0 else left / right


def _call(node: Call, lookup: Lookup, registry: Registry) -> Value:
    func = registry.get(node.name)
    if func is None:
        return CellError.NAME
    numbers: list[float] = []
    for arg in node.args:
        if isinstance(arg, RangeRef):
            values = [lookup(addr) for addr in arg.cells.addresses()]
            values = [v for v in values if v is not None]  # empty cells are skipped
        else:
            values = [evaluate(arg, lookup, registry)]
        for value in values:
            if isinstance(value, CellError):
                return value
            numbers.append(value)
    try:
        return func(numbers)
    except ZeroDivisionError:
        return CellError.DIV0
