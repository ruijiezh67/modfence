"""One-shot and interactive command-line interface."""

import sys

from calc.evaluator.evaluate import EvalError, evaluate
from calc.lexer.scanner import LexError
from calc.parser.parser import ParseError, parse


def format_number(value: int | float) -> str:
    """Render a result without float noise (3.0 -> 3, 0.1+0.2 -> 0.3)."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.10g}"
    return str(value)


def calculate(source: str) -> str:
    """Evaluate ``source`` and return the formatted result."""
    return format_number(evaluate(parse(source)))


def run_line(source: str) -> int:
    """Print the result or an error message for one expression."""
    try:
        print(calculate(source))
    except (LexError, ParseError, EvalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one expression from argv, or start a REPL when none is given."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        return run_line(" ".join(args))
    while True:
        try:
            line = input("calc> ").strip()
        except EOFError:
            return 0
        if line in ("quit", "exit"):
            return 0
        if line:
            run_line(line)
