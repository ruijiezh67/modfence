# How modfence works

Everything below runs on your machine. Only the steps marked "model call" talk to a model, and they go through your own Claude Code CLI.

## The map

| Level | What you see | How it is built |
|---|---|---|
| **1 Modules** | About 7 boxes to start: the jobs the system does (observer, inference, memory, repair ...). Saved as `MODULES.md`, they become the modules your team and every agent share; you split, merge and add them as the project needs. | Code cuts *blocks* that must stay together: folder and file-name groups, with copies of the same code joined (`roles.blocks`). One model call sorts whole blocks into modules and names them (`roles.functions`); it cannot split a block. Once `MODULES.md` exists, the map reads it instead. |
| **2 Roles of a module** | The module as a frame around its roles; the other modules sit outside it, the ones it uses above, the ones using it below. | Inside each module, blocks are merged by what changed together in git, what imports what, and shared folders (`roles.suggest_areas`), at most 6 roles. One small model call only names them. A role named like its module reads as "<name> core". |
| **3 Parts of a role** | At most 8 parts: files grouped by the word their names share, else by folder. | Deterministic (`roles.role_parts`). |

**Lines** between boxes, each with its evidence on hover:

| Line | Meaning | Source |
|---|---|---|
| solid | imports, thicker for more import lines, faint when weak | `ast` imports, with file:line receipts (`analyze.py`) |
| dashed | an HTTP call or a started file | a URL path matched to a route decorator, or a file named by path (`roles.runtime_links`) |
| dash-dot | copied code | the same file name in another top folder sharing half its lines |
| dotted | changed together in git | only for a box with no other link, with the commit count |

Boxes with no link at all are not vertices: they sit as chips under the map. Entry points (`main`, `*_main`), HTTP route files and shared config (`settings`, `config` used by 2+ roles) are not boxes either; the side bar lists them under the role that starts, serves or reads them, and they are read-only by default.

Layout: boxes read top to bottom like a tree, from what others use (cores) to what uses them (front ends, scripts), in at most 4 rows; inside a row a stress layout (Gansner, Koren and North 2004) keeps linked boxes near each other.

## A task, fenced just in time

You give Claude Code a task as usual. The plugin's `UserPromptSubmit` hook (`jit.py`) reads it at that moment and scores every function of every module in `MODULES.md`: 3 per task word in its name, 1 per word in its body, plus words in its file's name; a module scores its best three. The best module is fenced (and the second when it scores at least 3/4 as well), through `.modfence/fence.json`, which the plugin's `PreToolUse` hook enforces on edit tools only. The agent gets one short paragraph: the modules it may edit and the three likely places (file:line, function); you get one line: the modules, the functions behind the guess and the other candidates. Nothing happens without `MODULES.md`, on a fence you set yourself (`modfence fence`, kept), or on a follow-up whose words point nowhere (the task's fence stays).

An edit outside the fence is blocked and logged; the map's top bar shows it with *Allow module X* (widens the fence for the same conversation) and *Refuse*, next to the task, the evidence and the other candidates, each one click away. When the agent stops, the receipt (`receipt.py`, the plugin's `Stop` hook) says what changed and what may break.

The older hand-off (`runner.Handoff`: snapshot, a line to paste, *Review changes*, revert) and headless runs (`/api/ask`, `done_check.py`) remain in the server; the page no longer starts them.

## An agent you run yourself (Claude API, Agent SDK, any tool loop)

The same fence, with no plugin: call two functions where your loop already decides things. Checked with the Agent SDK
(0.2.180, Haiku, one task): the edit inside the task's module went through, the one outside was denied and logged as a
request, $0.007.

```python
import modfence
f = modfence.fence_for(task, project)          # fences the task's module; f["context"] goes to the model
why = modfence.check_edit(path, project)       # before writing a file: None, or the reason to send back instead
```

With the Agent SDK, return `f["context"]` as `additionalContext` from a `UserPromptSubmit` hook and `why` as a `deny`
from a `PreToolUse` hook on `Edit|Write|MultiEdit|NotebookEdit`. A chat window that runs no tools (claude.ai, a web
chat) has nothing to block: there the receipt, from git, is the check.

## Parts of the code

| Part | File | What it does |
|---|---|---|
| Graph | `analyze.py` | Parses every `.py` file with `ast`. An edge A → B exists when a file in A imports a file in B, with the file, line and imported name of each import. Functions are fingerprinted before and after a run to name what changed. No model draws the graph. |
| Roles and functions | `roles.py` | Blocks, functions, roles, parts, file kinds, runtime links, co-change. Measured in [EVALUATION.md](EVALUATION.md) sections 6 and 7. |
| Brief | `brief.py` | The AI-only document of a fence: what it uses and what others use from it, encoded for tokens (88/88 comprehension probe), plus the contract check. |
| Runs | `runner.py` | Starts `claude -p --output-format stream-json`, streams events, diffs the project after the run, stores each version's files before and after. `Handoff` does the same around an agent you run yourself. |
| Map as text | `handoff.py` | The project map for any agent, capped at about 1.5k tokens, no model call. |
| Modules file | `modules.py` | Reads and writes `MODULES.md`: owner of a path by the longest matching line, the map's areas compressed to folder lines, the map synced to the file. |
| Plugin | `.claude-plugin/`, `hooks/`, `commands/`, `skills/`, `plugin/cli.py` | The Claude Code plugin: the fence hook (`modfence guard`), the receipt as a Stop hook, two slash commands, one skill. |
| Receipt | `receipt.py` | `modfence receipt`: the working tree against a git revision, as parts of the map changed, parts that use them, contract breaks, files outside the fence and tests to run; exit 1 on a break. |
| Fence | `scope_guard.py` | The hook. While the UI has a fence set it is also written to `.modfence/fence.json` and `.claude/settings.local.json`, so agents you start yourself are fenced too. |
| Done check | `done_check.py` | Test selection, the test gate, one send-back. |
| Project docs | `docs.py` | Places the project's markdown files on the roles they name; staleness; lessons. |
| Skills | `skills.py` | The project's libraries, matched to skills.sh skills; installs one into the project only. |
| Purposes | `purpose.py` | Docstring first line, else a one-line summary from a small model, cached by file hash. |
| Server | `server.py` | `http.server` on 127.0.0.1 only; requests need a localhost `Host`, writes an `X-Modfence` header. Plain HTML, CSS and JS in `web/`, no build step. |

**State** lives in `<project>/.modfence/` (git-ignored automatically): roles, sessions and run logs per fence, `runs/<id>/` with each version's files before and after, caches.

## Settings

| Setting | Default |
|---|---|
| `--port` | 8765 |
| `--test-cmd` / `MODFENCE_TEST_CMD` | pytest if configured, else `unittest` on `tests/` or `test/`, using the project's `.venv` |
| `--claude` / `CLAUDE_BIN` | the Claude Code CLI on PATH or in the VS Code bundle |
| `MODFENCE_LANGUAGE` | the language of the agent's replies in modfence runs (your Claude Code setting otherwise) |
