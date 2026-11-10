---
description: Fence agents in this project to one module of MODULES.md, or lift the fence (--off)
argument-hint: <module> | --off
allowed-tools: Bash(python:*), Bash(python3:*)
---
!`P=python; command -v python >/dev/null 2>&1 || P=python3; "$P" "${CLAUDE_PLUGIN_ROOT}/plugin/cli.py" fence $ARGUMENTS; true`

Above is the fence as modfence set it. While it is on, edits outside that module are blocked for every agent in this project. If the task needs another module, finish the part inside the fence, then ask the user to widen it.
