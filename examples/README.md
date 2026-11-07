# modfence examples

Five small Python projects for demonstrating modfence. Each is a package whose modules are separate subpackage directories with real absolute imports between them, so the module graph is meaningful. All use Python 3.10+; `00-iris` and the next three use the standard library only, and `04-tinygpt` needs PyTorch. Each has a README (module table, run, test) and a TASKS.md with five tasks from easy to hard, at least one of which crosses several modules.

| Project | Level | Modules | What it teaches about modular design |
|---|---|---|---|
| [`00-iris`](00-iris/) | Start here (ML) | 6: `data`, `features`, `model`, `train`, `evaluate`, `cli` | An ML pipeline with the standard library only. The stages are independent and pass plain lists; `cli` runs them in order. Tasks range from a new model (`model` only) to save/load and early stopping across two modules. |
| [`01-calculator`](01-calculator/) | Easy | 4: `lexer`, `parser`, `evaluator`, `cli` | A pipeline. Each stage depends only on the one before it, and data flows one way (text, tokens, tree, value). Tasks show how one feature (a new operator) touches every stage. |
| [`02-library`](02-library/) | Medium | 5: `domain`, `storage`, `services`, `reports`, `cli` | A layered architecture. `domain` depends on nothing, `storage` hides persistence behind an interface, `services` and `reports` sit on top of it, and `cli` wires everything together. Tasks show features that stay in one layer versus features that cut through all of them. |
| [`03-spreadsheet`](03-spreadsheet/) | Hard | 7: `cells`, `formula`, `functions`, `graph`, `engine`, `io`, `cli` | A graph of cooperating libraries. Leaf modules (`cells`, `functions`, `graph`) are reusable on their own, `engine` composes them, and `io` and `cli` are thin edges. Tasks mix leaf-only changes with changes that must be coordinated across four modules. |
| [`04-tinygpt`](04-tinygpt/) | Hard (ML) | 6: `config`, `data`, `model`, `train`, `eval`, `cli` | A training codebase, the shape of nanoGPT-style repos split into packages. `model` and `data` are independent, `train` and `eval` build on them, `cli` wires a run together. Tasks range from a sampling tweak inside `eval` to gradient accumulation (`config` + `train`) and a KV cache (`model` + `eval`). |

Run the tests of any project from its own folder:

```
python -m unittest discover -s tests -t .
```
