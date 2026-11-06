"""Static analysis of parsed formulas."""

from sheet.cells.address import CellAddress
from sheet.formula.nodes import BinOp, Call, Neg, Node, RangeRef, Ref


def dependencies(node: Node) -> set[CellAddress]:
    """Every cell the formula reads, with ranges expanded."""
    if isinstance(node, Ref):
        return {node.address}
    if isinstance(node, RangeRef):
        return set(node.cells.addresses())
    if isinstance(node, Neg):
        return dependencies(node.operand)
    if isinstance(node, BinOp):
        return dependencies(node.left) | dependencies(node.right)
    if isinstance(node, Call):
        found: set[CellAddress] = set()
        for arg in node.args:
            found |= dependencies(arg)
        return found
    return set()
