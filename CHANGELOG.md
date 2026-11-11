# Changelog

## Unreleased

- **Stops only where a guess would cost.** The protocol names the pattern (a comparative like bigger, longer, fewer with no number), says "change nothing yet", and skips code tweaks where any sensible value would do. Measured: -33% to -41% cost on experiment settings (`bench/rework_probe.py`), -8% on TinyDB code constants (no stops).
- **An open question holds the agent's edits** until the person answers (on the page or in the chat); intents work without a shell; if no page is served, `mod wait` returns at once and the agent says how to answer. The answer never reaches the agent contradicted (shared values only) or as a traceback.
- **JIT fence picker:** constants at module or class level count; queries ~ query; intent files are always writable. All 11 probe tasks fence the right module. The fence now costs nothing measurable on rich (-1% cost, +3% time).
- **Receipt hook:** exits after git status when nothing changed (2.7 s to 0.85 s on rich), and keeps a parse cache in `.modfence/` (one change: 3.3 s to 1.8 s).
- **Intents page:** a pick button per reading, source glyphs on every value, focus kept across redraws, Enter belongs to the focused control, a top strip on narrow panes, the fence shown beside where the agent stopped, chat answers counted.
- **Intents page, round 2.** A caption per column (what you said / which one did you mean / where the agent is); your words shown next to what they were taken to mean; a reading's values editable in place; the stopped step shows the picked reading's own scale; a countdown of the agent's wait, then "your agent stopped waiting"; your answer habits on the Project view (first shown picked, values changed, own words, median time). The agent now gets the picked reading's values and scale, not only its name (a Haiku probe followed an edited value, 37, to the config). An answer given after the wait ran out comes with your next message.
- **JIT fence: a module is found by its own name and purpose.** On TinyDB, "add an update operation toggle(field)" was fenced to the table code and the edit was denied (task failed); it now picks the operations module (3/3). Hooks start Python with `-S`. TinyDB probe (Haiku, 3 tasks, edit-only): no cost saving on a 4,900-line project, 2-3 s slower per task from hook start-up on Windows.
- **Map:** the legend draws links as lines, the path bar is a plain path, the fence hatch is light enough to read through.
- **`.mod`: the agent says what it would otherwise guess.** `.mod/project.mod` replaces `MODULES.md` (modules plus the settings you confirmed). When your request leaves settings open (a short prompt for an experiment, a config, a run, results going into docs, something hard to undo), the agent writes an intent `.mod`: your words, 2-3 readings with evidence, each setting with its source (said, default, remembered with its date, guessed), the scale and a plan slice, then runs `modfence mod wait <id>`. The Intents page (`/mod.html`) shows it on one screen: your words with the settings they gave numbered on them, the readings side by side by their differences (shuffled, none preselected or recommended), guesses and memory first, the scale with cost and time. Keys 1-3 pick, Enter continues, and the waiting agent goes on at once (it waits up to 110 s, within the default Bash timeout and the prompt cache). A setting you confirm is never asked again. A SessionStart hook gives a new or compacted session the project state from `.mod` instead of conversation memory. `.mod/` stays out of git unless you share it. Checked with one Haiku probe: a vague "re-run the training with more epochs" became a 2-reading intent, and the config changed only after the answer ($0.009).
- **Map:** opens fast (each project's roles are warmed at start), says what it is reading instead of a blank page, and links the Intents page ("Your agent waits (n)").
- **The task picks the fence (just in time).** You give Claude Code a task as usual; the plugin's `UserPromptSubmit` hook (`modfence jit`) finds the module of `MODULES.md` the task most likely lives in from its words and the code (no model), fences the agent to it (two modules when two score alike), tells the agent where to start (3 functions with file:line) and tells you which module, why and what else it could be. A fence you set yourself is kept; a follow-up like "continue" keeps the task's fence. The map's top bar shows the task's fence, its evidence and the other candidates (a click switches) and the agent's requests (Allow module, Refuse). The *Fence & copy* button is gone: no fence before a task. `modfence jit "TASK"` shows what it would pick. Measured on rich (round 2, 60 runs): a one-line fence with 3 likely places cost 25% less and took 46% less time than plain Claude Code (14/15 vs 15/15 passing); to be repeated, as every arm cost more than in round 1.
- **The goal is fewer tokens and less time for the same coding goal** (golden rules, rule 6). Several people working at once is now a side goal.
- **The map has one button per step.** Pick a box, *Fence & copy for my agent*, allow or refuse a request, *Review changes*, revert with a second click. Removed from the page: the headless run composer, History, Run tests, theme, help, zoom buttons, skills, agents, copy map and role editing. VS Code's Simple Browser blocks `prompt()` and `confirm()`, so several of those buttons did nothing there; nothing on the page uses a dialog now. A module fence now shows its review (the log was keyed by the box's files and never matched), the map rescans when you return to it, and a second hand-off no longer orphans the first.
- **The fence hook starts only on edits.** It matched every tool, so each read, search and command waited for a Python process (0.35 to 0.7 s on Windows). The map of a 400-file project loads in 0.5 s instead of 6.

- **modfence draws itself.** `MODULES.md` at the root is modfence's own map (map, fence, review, interface, plugin, benchmarks, examples), generated by modfence and edited by hand. Two graph fixes it needed: a folder of standalone projects (examples/) is one block, and a flat package whose file names share no word is cut by its import communities. A dot folder (`.claude-plugin/`) now matches in MODULES.md, and the out-of-date check reads every tracked file, not only Python.
- **Claude Code plugin.** `/plugin install modfence --marketplace ruijiezh67/modfence`: a Stop hook that blocks a round once when the receipt finds a broken contract, a new cross-module dependency or an edit outside the fence; the fence hook; `/modfence:receipt`, `/modfence:fence <module>`; a short skill for repositories with `MODULES.md`. No pip install: the plugin runs modfence from its own folder. It does nothing in a project without `MODULES.md` or a fence.
- **`MODULES.md`.** *Save as MODULES.md* on the map writes the first-level modules (name, purpose, folders and files, the longest line winning; tests belong to no module) for the team, the agent, the fence and the receipt. The map reads it back and writes edits to it.
- **`modfence fence <module>` / `--off`.** A fence from the terminal, by module name.
- **Receipt: new dependencies.** A part of the map that now imports a part it never imported before is reported.
- **`modfence receipt`.** What a change touched and what it may break, in the terminal, from git: the parts of the map it changed, the parts that use them, names another module uses whose signature broke (with the lines that use them), files outside the fence, and the tests to run. No UI, no model. Exits 1 on a broken contract or an edit outside the fence, so a hook or CI can block on it.
- **Hand-off approvals.** When the fence stops your own agent, the map shows the file as a request; Allow widens the fence for the agent already working.
- **Curved links** from the side of a box, spread so they do not cross at it.

## 0.3.0 (2026-11-09)

The map became a place to direct an agent from, and every part of a run became visible.

- **Hand to my agent is the default.** modfence fences the box for the agent you already use (Claude Code, Cursor, Codex), copies the task with a fence note, marks the boxes it changes as it goes, and reviews the result like a run. *Run here* still starts Claude Code headless.
- **The map as text for agents.** *Copy brief for agents* gives a box's interfaces and the whole project map in about 1.5k tokens.
- **Functions first.** The first level is at most 7 functions (observer, inference, memory ...), sorted by one model call from blocks that code cuts and that keep copies of the same code together; inside a function, roles are grouped by git co-change, imports and folders and only named by a model.
- **Links with evidence.** HTTP calls matched to route decorators, files started by path, copied code, and co-change from git join imports, so separate programs are no longer islands. Boxes with no link are listed apart.
- **Readable layout.** Cores on top, what uses them below, in at most 4 rows; inside a function, its roles sit in a frame and the other functions outside. Hovering a line explains it in plain words.
- **Ask in the side bar.** The picked box takes your instruction directly; the map stays where it is.
- **Ask before crossing the fence.** The agent stops and asks for files outside the fence; you allow a file, a role, or nothing.
- **Routing and the lean rule.** Self-contained tasks build at once, others plan first; every edit run carries a short lean rule (output tokens −9% measured).
- **Tests.** The done check runs the tests covering the fence and its users, and sends the agent back once when it adds branching logic without a test.
- **Review.** Drafted commit messages, an optional review run, and lessons written into the project's docs.
- **Project docs and skills.** The project's markdown docs are placed on the roles they describe and passed to runs as pointers; skills from skills.sh are matched to the project's libraries and added to the project on a click.
- **Agents you start yourself** are fenced too while a fence is set.
- Golden rule 5: modules isolate, and every round says which modules it changed.

## 0.2.0 (2026-11-08)

- Sealed runs: the agent sees other modules only through a compact brief.
- Module contract check after each run.
- Roles and parts as the two levels of the map; function graphs removed.

## 0.1.0 (2026-11-06)

- First release: the module graph, fenced Claude Code runs, plan and build, History with diff and revert.
