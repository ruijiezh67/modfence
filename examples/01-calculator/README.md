# 01-calculator

A small arithmetic calculator. It reads an expression, splits it into tokens, parses the tokens into a syntax tree with a recursive-descent parser, and evaluates the tree. It supports `+ - * /`, parentheses, unary minus, integers and decimals. It does not yet support exponents, variables or functions.

| Module | Responsibility | Depends on |
|---|---|---|
| `calc.lexer` | Token types and the scanner that turns text into tokens | none |
| `calc.parser` | AST node types and the recursive-descent parser | `lexer` |
| `calc.evaluator` | Walks the AST and computes a number, raising clear errors | `parser` |
| `calc.cli` | One-shot and REPL front end, result formatting | `lexer`, `parser`, `evaluator` |

## Run

```
python -m calc "1 + 2*3"     # prints 7
python -m calc               # starts a REPL
```

## Test

```
python -m unittest discover -s tests -t .
```

Python 3.10+, standard library only.
