# Tasks for 03-spreadsheet

Each task lists its target module(s). Acceptance examples use the REPL commands `set CELL TEXT` and `get CELL`, or the equivalent `Sheet.set` and `Sheet.value` calls.

## 1. COUNT function (single module: `functions`)

Target: `sheet.functions` only.

Build: add `COUNT` (the number of numeric arguments) to `builtins.py` and register it in `default_registry`. Empty cells inside ranges are already skipped by the engine, so COUNT counts only filled cells.

Acceptance:
- `default_registry().get("COUNT")([4, 8, 15])` returns `3`
- `default_registry().get("count")([])` returns `0`
- With `A1=1`, `A2=` (empty), `A3=7`: `set B1 =COUNT(A1:A3)` then `get B1` prints `2`

## 2. Fast range expansion limit (single module: `cells`)

Target: `sheet.cells` only (`ranges.py`).

Build: `CellRange.addresses()` currently materializes every cell, so `A1:ZZ9999` allocates about 7 million objects. Add `CellRange.size` (rows times columns) and make `parse_range` and `make_range` raise `InvalidAddress` when the size exceeds 100000.

Acceptance:
- `parse_range("A1:B3").size == 6`
- `parse_range("A1:ZZ9999")` raises `InvalidAddress`
- `parse_range("A1:A100000")` raises `InvalidAddress` because the row is out of bounds, and `parse_range("A1:CV1000")` (100000 cells exactly) succeeds

## 3. Cycle path in the error (single module: `graph`)

Target: `sheet.graph` only.

Build: add `DependencyGraph.find_cycle(node) -> list | None` returning one dependency cycle through `node` as an ordered list starting and ending with `node`, or `None`. Use an iterative search.

Acceptance:
- Edges `a depends on b`, `b depends on c`, `c depends on a`: `find_cycle("a")` returns `["a", "b", "c", "a"]`
- A self-loop on `a`: `find_cycle("a")` returns `["a", "a"]`
- A chain `a depends on b`, `b depends on c`: `find_cycle("a")` returns `None`

## 4. String values and the CONCAT function (crosses modules: `formula`, `functions`, `engine`, `io`)

Target: `sheet.formula`, `sheet.functions`, `sheet.engine`, `sheet.io`.

Build: cells may hold text. Formula: string literals in double quotes and a `StringLit` node. Functions: functions receive mixed values, SUM/MIN/MAX/AVG ignore text, and a new `CONCAT` joins its arguments. Engine: `Value` becomes `float | str | CellError`, `Sheet.set` stores any non-numeric non-formula text as a string, and arithmetic on text gives `#VALUE!` (a new `CellError`). IO: CSV import and export keep text cells (including text that starts with a quote or comma).

Acceptance:
- `set A1 hello` then `get A1` prints `hello`
- `set B1 =CONCAT(A1, " world")` then `get B1` prints `hello world`
- `set C1 =A1+1` then `get C1` prints `#VALUE!`
- With `A1=hello`, `A2=4`, `A3=6`: `=SUM(A1:A3)` is `10` and `=AVG(A1:A3)` is `5`
- A CSV round trip of a sheet containing `hello, "quoted"` as text restores the same value

## 5. IF function with lazy evaluation and comparisons (crosses modules: `formula`, `functions`, `engine`, `graph`)

Target: `sheet.formula`, `sheet.functions`, `sheet.engine`, `sheet.graph`.

Build: `=IF(condition, then, else)` plus the comparison operators `< > <= >= = <>` (lowest precedence, result 1 or 0). Formula: lexer and parser support for comparisons. Engine: IF evaluates only the chosen branch, so `=IF(1, 5, 1/0)` is `5`. Functions: register the name `IF` so the engine can detect it (the evaluation itself is special-cased in the engine, because registry functions only see evaluated arguments). Graph: the dependency set stays static (both branches count as dependencies), and a test must show that a cycle through an untaken branch is still reported as `#CYCLE!`.

Acceptance:
- `set A1 3`, `set B1 =IF(A1>2, 10, 20)`, then `get B1` prints `10`
- `set A1 1` then `get B1` prints `20`
- `set C1 =IF(1, 5, 1/0)` then `get C1` prints `5`
- `set C1 =IF(0, 5, 1/0)` then `get C1` prints `#DIV/0!`
- `=1<2` is `1`, `=2<=1` is `0`, `=3<>3` is `0`
- `set D1 =IF(1, 7, D1)` then `get D1` prints `#CYCLE!`
