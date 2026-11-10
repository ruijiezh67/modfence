---
description: What this round changed, by module, and what it may break (no model call)
allowed-tools: Bash(python:*), Bash(python3:*)
---
!`P=python; command -v python >/dev/null 2>&1 || P=python3; "$P" "${CLAUDE_PLUGIN_ROOT}/plugin/cli.py" receipt; true`

Above is the modfence receipt of the working tree against HEAD. If it reports a broken contract, a new dependency or a file outside the fence, explain each one in a line: fix it, or say why it is intended.
