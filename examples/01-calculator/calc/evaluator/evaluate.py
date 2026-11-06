"""Tree-walking evaluator."""

from calc.parser.nodes import BinOp, Node, Num, UnaryOp


class EvalError(ArithmeticError):
    """Raised when an expression is well formed but cannot be computed."""


def evaluate(node: Node) -> int | float:
    """Return the numeric value of ``node``."""
    if isinstance(node, Num):
        return node.value
    if isinstance(node, UnaryOp):
        if node.op == "-":
            return -evaluate(node.operand)
        raise EvalError(f"unknown unary operator {node.op!r}")
    if isinstance(node, BinOp):
        left, right = evaluate(node.left), evaluate(node.right)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise EvalError("division by zero")
            return left / right
        raise EvalError(f"unknown operator {node.op!r}")
    raise EvalError(f"cannot evaluate {type(node).__name__}")
