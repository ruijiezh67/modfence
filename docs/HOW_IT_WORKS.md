# How modfence works

Everything below runs on your machine. Only the steps marked "model call" talk to a model, and they go through your own Claude Code CLI.

## The map

| Level | What you see | How it is built |
|---|---|---|
| **1 Functions** | At most 7 boxes: the jobs the system does (observer, inference, memory, repair ...). | Code cuts *blocks* that must stay together: folder and file-name groups, with copies of the same code joined (`roles.blocks`). One model call sorts whole blocks into functions and names them (`roles.functions`); it cannot split a block. |
| **2 Roles of a function** | The function as a frame around its roles; the other functions sit outside it, the ones it uses above, the ones using it below. | Inside each function, blocks are merged by what changed together in git, what imports what, and shared folders (`roles.suggest_areas`), at most 6 roles. One small model call only names them. A role named like its function reads as "<name> core". |
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

## A hand-off (the default)

Most people already work in an agent of their own, so modfence does not need to be the chat. *Hand to my agent* snapshots the project (`runner.Handoff`), arms the fence for every agent started in it (`.modfence/fence.json` plus the hook in `.claude/settings.local.json`) and copies the instruction with the fence note (`Handoff.prompt_text`, about 500 tokens). While your agent works, the map polls the files it changed and marks their boxes. *Review changes* closes the hand-off: the same review as a run below (changed functions, contract check, commit draft, revert), then the fence comes off. A reload finds an open hand-off again; a restarted server clears any fence left behind.

*Copy brief for agents* puts a box's brief (`brief.py`) on the clipboard, and the whole project as about 1.5k tokens of text (`handoff.py`: functions and roles, the strongest links between functions, copies to keep in sync, read-only files, the test command, recent runs, docs per function), for any agent or a new session.

## A run (Run here)

modfence starts Claude Code itself, headless.

1. **Route.** A fence inside one role that nothing outside depends on (no copies, HTTP callers or co-change partners outside) builds at once. Anything else plans first: the agent reads, asks only what is unclear, and lists the functions it will change. The composer says which path and why; one click switches.
2. **Build, fenced and sealed.** A `PreToolUse` hook (`scope_guard.py`) denies edits outside the fence after resolving `..` and symlinks, and fails closed. Sealed (the default), the agent cannot read other modules' code either; it gets a brief of what they offer and what the fence must keep working (`brief.py`, no model call). Every edit run also carries the lean rule (`runner.LEAN_RULE`) and pointers to the project docs placed on the fence (`docs.py`).
3. **Ask before crossing.** If the agent needs a file outside the fence, it stops and writes `NEED <path>: <why>`. The run ends with a card per file; *Allow this file* or *Allow all of <role>* continues the same conversation with the fence widened.
4. **Done check.** A `Stop` hook (`done_check.py`) runs the test files that cover the fence and the modules using it (else the whole suite), and sends the agent back once if they fail, or if it added branching logic without touching a test.
5. **Review.** The run's changed functions, which boxes it changed (green, with +/- lines) and which use the changed code (pale yellow), the contract check (names other modules used whose signature changed), a drafted commit message, a revert, an optional review run, and a box to write a lesson into the project's docs.

## Parts of the code

| Part | File | What it does |
|---|---|---|
| Graph | `analyze.py` | Parses every `.py` file with `ast`. An edge A → B exists when a file in A imports a file in B, with the file, line and imported name of each import. Functions are fingerprinted before and after a run to name what changed. No model draws the graph. |
| Roles and functions | `roles.py` | Blocks, functions, roles, parts, file kinds, runtime links, co-change. Measured in [EVALUATION.md](EVALUATION.md) sections 6 and 7. |
| Brief | `brief.py` | The AI-only document of a fence: what it uses and what others use from it, encoded for tokens (88/88 comprehension probe), plus the contract check. |
| Runs | `runner.py` | Starts `claude -p --output-format stream-json`, streams events, diffs the project after the run, stores each version's files before and after. `Handoff` does the same around an agent you run yourself. |
| Map as text | `handoff.py` | The project map for any agent, capped at about 1.5k tokens, no model call. |
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
