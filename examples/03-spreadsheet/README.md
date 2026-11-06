# 03-spreadsheet

A tiny spreadsheet engine. Cells hold numbers or formulas such as `=A1+B2*2` and `=SUM(A1:A3)`. Setting a cell parses its formula, records which cells it reads in a dependency graph, and recalculates only that cell and the cells downstream of it, in topological order. Problems show up as error values (`#CYCLE!`, `#REF!`, `#DIV/0!`, `#NAME?`, `#ERR!`) that propagate to dependents. It has no IF(), no string values, no undo/redo and no relative-reference copy/paste yet.

| Module | Responsibility | Depends on |
|---|---|---|
| `sheet.cells` | Cell addresses (`A1`) and ranges (`A1:B3`) | none |
| `sheet.formula` | Formula lexer, parser, AST and dependency extraction | `cells` |
| `sheet.functions` | SUM, MIN, MAX, AVG and the function registry | none |
| `sheet.graph` | Generic dependency graph, topological order, cycle detection | none |
| `sheet.engine` | Cell storage, evaluation, incremental recalculation, error values | `cells`, `formula`, `functions`, `graph` |
| `sheet.io` | CSV import and export of formulas or values | `cells`, `engine` |
| `sheet.cli` | Line-based REPL | `cells`, `engine`, `io` |

## Run

```
python -m sheet
sheet> set A1 2
sheet> set A2 3
sheet> set A3 =SUM(A1:A2)*2
sheet> show
sheet> export out.csv values
sheet> quit
```

REPL commands: `set CELL TEXT`, `get CELL`, `show`, `import FILE`, `export FILE [values]`, `quit`.

## Test

```
python -m unittest discover -s tests -t .
```

Python 3.10+, standard library only.
