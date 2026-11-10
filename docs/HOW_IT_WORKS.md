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

## A hand-off

Most people already work in an agent of their own, so modfence is not the chat. Click a box, then *Fence & copy for my agent*: modfence snapshots the project (`runner.Handoff`), arms the fence for every agent started in it (`.modfence/fence.json` plus the hook in `.claude/settings.local.json`, run only on edit tools), writes the fence note to `.modfence/agent/<box>.md` and copies one line to paste into the agent's chat before the task. While the agent works, the map marks the boxes it changed. An edit outside the box is blocked and shows up as a card: *Allow module X* widens the fence for the same conversation, *Refuse* keeps it. *Review changes* closes the hand-off: the changed functions, the boxes that use them, the contract check (names other modules used whose signature changed) and files changed outside the fence, then the fence comes off. *Revert this round* puts the files back (a second click confirms: the editor's browser blocks dialogs). A reload finds an open hand-off again; a second hand-off waits until the first is reviewed.

The page has one button per step of that loop and nothing else. The map reads the project again when you come back to it, so an edit to `MODULES.md` shows without a refresh button.

The server still has the older headless path (`/api/ask`, `claude -p` started by modfence, with plan, build and the done check in `done_check.py`); the page no longer offers it.

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
