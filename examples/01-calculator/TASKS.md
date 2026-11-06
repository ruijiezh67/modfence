# Tasks for 01-calculator

Each task lists its target module(s). Acceptance examples use the one-shot CLI form `python -m calc "<input>"` and its printed output, or the equivalent function call.

## 1. Exact integer division (single module: `evaluator`)

Target: `calc.evaluator` only.

Build: when both operands of `/` are integers and the division is exact, return an `int` instead of a float. Inexact divisions still return a float. Also reject results whose absolute value exceeds 1e300 with `EvalError("result too large")`.

Acceptance:
- `evaluate(parse("6 / 3"))` returns `2` and `type(...)` is `int`
- `evaluate(parse("7 / 2"))` returns `3.5`
- `evaluate(parse("6.0 / 3"))` returns `2.0` (a float)
- `evaluate(parse("1e300"))` is not valid input, so use `BinOp("*", Num(1e200), Num(1e200))` and expect `EvalError`

## 2. Friendlier number formatting (single module: `cli`)

Target: `calc.cli`.

Build: make `format_number` print at most 10 significant digits and use plain notation for results below 1e15 and scientific notation above. Add a `--precision N` option to the one-shot command.

Acceptance:
- `python -m calc "1/3"` prints `0.3333333333`
- `python -m calc --precision 3 "1/3"` prints `0.333`
- `python -m calc "10000000000 * 10000000000"` prints `100000000000000000000`

## 3. Better error messages with a caret (single module: `parser`)

Target: `calc.parser`.

Build: make `ParseError` carry the position of the offending token (`error.pos`) and the original source, and add a method `error.render()` that returns the source line followed by a line with a caret under the position.

Acceptance:
- `parse("1 + * 2")` raises `ParseError` with `pos == 4`
- `error.render()` returns `"1 + * 2\n    ^"`
- `parse("(1 + 2")` raises `ParseError` with `pos == 6`

## 4. Exponent operator `^` (crosses modules: `lexer`, `parser`, `evaluator`)

Target: `calc.lexer`, `calc.parser`, `calc.evaluator`.

Build: add `^` (right associative, binds tighter than `*` and `/`, looser than unary minus on its left: `-2^2` is `-4`). Lexer: a new token kind. Parser: a new grammar level between `unary` and `primary`. Evaluator: the new operator, with `0 ^ -1` raising `EvalError`.

Acceptance:
- `python -m calc "2 ^ 3"` prints `8`
- `python -m calc "2 ^ 3 ^ 2"` prints `512`
- `python -m calc "-2 ^ 2"` prints `-4`
- `python -m calc "2 * 3 ^ 2"` prints `18`
- `python -m calc "0 ^ -1"` exits with code 1 and prints an error

## 5. Variables and functions (crosses modules: `lexer`, `parser`, `evaluator`, `cli`)

Target: `calc.lexer`, `calc.parser`, `calc.evaluator`, `calc.cli`.

Build: identifiers, assignment `name = expr`, and the functions `sqrt(x)`, `abs(x)`, `max(a, b, ...)`. Lexer: identifier, `=` and `,` tokens. Parser: `Var`, `Assign` and `Call` nodes. Evaluator: an environment dict passed to `evaluate`, with an error for unknown names and a domain error for `sqrt` of a negative number. CLI: the REPL keeps one environment across lines.

Acceptance (REPL session, one input per line):
- `x = 4` prints `4`
- `x * 2` prints `8`
- `sqrt(x)` prints `2`
- `max(1, x, 3)` prints `4`
- `y + 1` prints an error mentioning `unknown name 'y'`
- `sqrt(0 - 1)` prints an error mentioning `negative`
