# Modules

The first-level modules of this project, written by modfence and edited by hand when needed.
Agents: work inside one module; a change in another module needs the user's approval.

## map
Builds the module map from the code: imports, git history, copies and runtime links, the roles and modules, and MODULES.md itself.
- modfence/analyze.py
- modfence/roles.py
- modfence/modules.py
- modfence/purpose.py

## fence
Keeps an agent inside one module: the edit hook, the runs through Claude Code, the done check and the escape-hatch viewer.
- modfence/scope_guard.py
- modfence/jit.py
- modfence/runner.py
- modfence/done_check.py
- modfence/show.py

## review
Says what a round changed and what it may break: the receipt, the quiz, and the briefs agents read.
- modfence/receipt.py
- modfence/quiz.py
- modfence/brief.py
- modfence/handoff.py

## interface
The map in the browser and the commands in the terminal: the local server, the page, the CLI, project docs and skills.
- modfence/server.py
- modfence/web/
- modfence/__main__.py
- modfence/__init__.py
- modfence/docs.py
- modfence/skills.py

## plugin
The Claude Code plugin: its hooks, slash commands, skill and entry point.
- plugin/
- hooks/
- commands/
- skills/
- .claude-plugin/

## benchmarks
Scripts that measure modfence against plain agent use: tokens, correctness, roles and modules.
- bench/

## examples
Small standalone projects to try the map on.
- examples/
