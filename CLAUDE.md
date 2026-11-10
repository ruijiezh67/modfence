# modfence

Before any change, read [docs/GOLDEN_RULES.md](docs/GOLDEN_RULES.md) and [MODULES.md](MODULES.md): modfence's own modules, drawn by modfence and edited by hand. Work inside one module per change and say which modules a change touched. Every revision must serve one of its seven rules. The core goal is module vibe coding: the same coding goal done with fewer tokens and in less time, by handing Claude Code one module at a time. Several people working at once without breaking each other is a side goal.

- Run the tests with `python -m unittest discover -s tests -t .`. They are deterministic and need no model or network.
- Standard library only (`dependencies = []`).
- Commit one logical change per commit, with a subject of 50 characters or fewer.
