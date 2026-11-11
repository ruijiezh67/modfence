<h1 align="center">modfence</h1>

<p align="center"><b>Module vibe coding for Claude Code.</b><br>
Each task is fenced to the module it needs, and the agent stops only where it would otherwise guess.</p>

<p align="center">
<a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue"></a>
<img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
<img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen">
<img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-brightgreen">
</p>

An agent given a short prompt guesses: which part of the code to touch, how many runs, which settings. When it guesses
wrong you find out late, after it edited three modules or ran the wrong experiment. modfence works on three things:

- **Goal drift.** When your words leave a setting open, the agent writes 2-3 readings of what you meant and waits. You pick one on a page, in seconds, instead of reading a long plan.
- **Scope creep.** Your task picks the module(s) it needs, and a hook blocks edits elsewhere until you allow them.
- **Comprehension debt.** A map of your project as at most 7 modules, and a receipt at every stop: what changed, what uses it, what may break.

The goal behind all three: the same coding goal for fewer tokens and less time. Whether it gets there is measured
below, including the runs where it did not.

## Quick start

```bash
pipx install git+https://github.com/ruijiezh67/modfence   # or: pip install git+https://...
cd path/to/your/python/project
modfence                                                  # the map, at http://127.0.0.1:8765
```

On the map, *Save modules* writes `.mod/project.mod`. Then add the plugin to Claude Code:

```
/plugin marketplace add ruijiezh67/modfence
/plugin install modfence@modfence
```

**You need** Python 3.10+ and Claude Code. No dependencies, no API key. The first open of a project asks one small model
call (through your Claude Code login, cents) to name its modules; everything else is computed locally.

## How you work

1. **Give Claude Code your task as usual.** The plugin reads it, picks the module it most likely lives in (from the task's words and the code, no model), fences the agent to it and tells it where to start. Claude Code shows you which module, why, and the other candidates. A follow-up like "continue" keeps the fence.
2. **If the task leaves something open, answer on a page.** The agent writes an intent to `.mod/intents/` and waits. The *Intents* page shows your words, the values you never said (marked as guessed or remembered, with the date), the 2-3 readings side by side with what each costs, and where the agent stopped. Nothing is preselected or ranked. Press 1-3 and Enter, edit a reading or one of its values, or say it in your own words. The agent continues at once; a setting you confirm is never asked again. Not at the page? Answer in the chat instead: until you answer, the agent may not edit. It stops only for values you would want exactly (an experiment's settings, a run, anything hard to undo); for a code tweak where any sensible value would do, it picks one and says which.
3. **If it needs another module, it says why.** The first edit outside is denied; the agent says why and tries again, and the file is listed on the map. A fence you set yourself is hard: the edit waits on the map for *Allow* or *Refuse*.
4. **When it stops, read the receipt.** The modules it changed, the code that uses them, interfaces it broke and edits outside the fence. A round that broke something is sent back once.

## What is built in

| | |
|---|---|
| **Map** | Your project as at most 7 modules, then roles, then files, drawn from imports, HTTP calls, copied code and git co-change. Every line keeps its evidence (file:line). Python only. |
| **Just-in-time fence** | A `UserPromptSubmit` hook picks the module(s) from the task; a `PreToolUse` hook blocks edits elsewhere. A fence you set yourself (`/modfence:fence <module>`) is never replaced. |
| **`.mod` files** | `.mod/project.mod`: modules and the settings you confirmed. `.mod/intents/*.mod`: one open question each. A new or compacted session reads `.mod` (about 440 tokens) instead of conversation memory. Git-ignored unless you share it. |
| **Intents page** | One column per decision, keyboard first. Readings follow Michelle Lam's just-in-time objectives (select, edit a reading or one of its values, delete, write your own; her weights are left out, as they read as scores); values show their source; your answer habits are counted, so rubber-stamping shows. |
| **Receipt** | `modfence receipt` and the plugin's `Stop` hook: changed modules, users of changed code, broken signatures, new cross-module imports, edits outside the fence. |
| **Your own tool loop** | `modfence.fence_for(task)` and `modfence.check_edit(path)` give an Agent SDK or raw API loop the same fence. |

Details: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md). Design rules: [docs/GOLDEN_RULES.md](docs/GOLDEN_RULES.md).

## Measured, not claimed

Write-ups in [docs/EVALUATION.md](docs/EVALUATION.md). The short version, newest first:

| Question | Result |
|---|---|
| When a prompt leaves a setting open, is stopping to ask cheaper than guessing and being corrected? (Haiku, a simulated person; a toy project's experiment settings and TinyDB's code constants, 3 tasks x 3 each) | On experiment settings, yes: with the current protocol, 40% lower cost and 8% less time over 18 runs per arm (toy project), the agent stopped every time and was never corrected; `bench/rework_probe.py` reproduces it. On code constants in TinyDB it did not pay (+6% to +12%) until the protocol stopped asking where any sensible value would do; then 13% lower cost over 18 runs, no stops (and +2% in a stricter, shorter setup). |
| Does the fence save cost or time on a larger project? (rich, about 30k lines, Haiku, 5 real past fixes, 35 runs per arm over three plugin versions, edit-only) | No saving. It cost 3-5% more and took 14-17% longer until the hooks were sped up and the picker fixed; the latest round is even (-1% cost, +3% time). Run afterwards, the commit's own tests passed in 35 of 35 fenced runs and 32 of 35 plain ones (all three on one task). |
| Does the plugin save cost or time on a small project? (TinyDB, 4,900 lines, Haiku, 3 tasks x 3 runs, edit-only) | No. Cost equal within noise; 2-3 s slower per task, from hook start-up (about 0.6 s per hook on Windows). |
| Does a one-line fence with likely places save on a larger one? (rich, Sonnet, 5 tasks x 3 runs) | 25% lower cost and 46% less time than plain Claude Code, 14/15 vs 15/15 passing; but plain cost 70% more in that round than in the round before, and the shipped plugin did not repeat it (row 2). The round before: the fence cost 54% more. |
| Does a fence save on well-specified tasks from a project's history? (private project, Sonnet, 4 tasks x 3) | No: 18-29% more cost. |
| What does a wrong fence cost? | The task. These probes found five ways the picker denied the right edit (words about how to work, a catch-all module, a constant it could not see, its own intent file, a plural); each is fixed and a regression test. |
| Does the fence stop scope creep? (rich, "tidy up anything else" appended, Haiku, 6 runs per arm) | Not shown yet: plain wandered in 0 of 6 runs; the fenced arm in 1, inside its own two-module fence. |
| Do the contract checks raise real alarms? | 8/8 flags on three git histories were real interface changes. |

## Limits

- **Python only** for the map.
- **The fence is a guess from words.** A catch-all module can outscore the right one, so a fence the task picked is soft: the agent may cross it on a second try after saying why, and you see the file on the map and in the receipt. A fence you set yourself is hard.
- **The hook sees file tools, not shell commands.** A script can still write outside the fence; the receipt reports it.
- **Hooks cost time:** about 0.6 s each on Windows, 4-5 per task.
- **Stops are judged by the agent.** Haiku stopped on "bigger" where its own guess was fine and not on "more often" where it was wrong, until the protocol limited stops to values people want exactly. Measured with a simulated person only.
- **No user study yet.**

## Help test it

1. Run it on a project you know well and give your agent one real task.
2. Open a [field report](https://github.com/ruijiezh67/modfence/issues/new?template=field-report.yml): how big the project is, whether the modules made sense, whether the fence or a question got in the way.
3. Bugs and ideas: [issues](https://github.com/ruijiezh67/modfence/issues).

**Privacy.** modfence runs on `127.0.0.1` only, has no telemetry, and sends nothing anywhere by itself. Code reaches a
model only through your own Claude Code. State lives in `<project>/.modfence/` and `<project>/.mod/`, both git-ignored
by default. See [SECURITY.md](SECURITY.md).

## Develop

```bash
git clone https://github.com/ruijiezh67/modfence && cd modfence
python -m unittest discover -s tests -t .
python -m modfence examples/*
```

The tests call no model. Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [golden rules](docs/GOLDEN_RULES.md) before a change.

## License

MIT. See [LICENSE](LICENSE).
