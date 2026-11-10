<h1 align="center">modfence</h1>

<p align="center"><b>Understand your project as modules, then direct the AI one module at a time.</b><br>
A local map of your code where every box is a fence for your coding agent.</p>

<p align="center">
<a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue"></a>
<img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
<img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen">
<img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-brightgreen">
</p>

AI agents now write most of the lines. What you still need to own is the shape: which part does what, what talks to what, and what a change touched. modfence gives you that shape and lets you act on it:

- **See** your project as at most 7 functions, then the roles inside each, drawn from your code and git history.
- **Fence** the agent to one box: it cannot edit, or by default even read, the rest. If it needs more, it asks you.
- **Review** every run by box and by function: what changed, what uses it, whether the tests passed, and a one-click revert.

## Quick start

```bash
pipx install git+https://github.com/ruijiezh67/modfence   # or: pip install git+https://...
cd path/to/your/python/project
modfence
```

Your browser opens `http://127.0.0.1:8765`. No project at hand? From a clone of this repo, `python -m modfence examples/*` opens five small example projects.

**You need** Python 3.10+. modfence has no dependencies and no API key. You keep working in your own agent (Claude Code, Cursor, Codex); modfence fences it and reviews what it did. With a logged-in [Claude Code](https://code.claude.com) CLI it can also run the agent itself, and the first open of a big project asks one small model call to name the functions (cents); everything else in the map is computed locally.

## How you work

**1. Pick a box and say what to change.** Click a function, open it, click a role. The side bar says what the box does, what it uses and what uses it, and takes your instruction right there.

**2. Read the lines.** Hover a line for what the link is and what it means for a change: imports, HTTP calls, copied code, or files that change together.

**3. Hand it to your agent, inside the fence.** *Hand to my agent* (Ctrl Enter) sets the fence and copies your instruction with a short fence note. Paste it into Claude Code, Cursor or Codex opened in the project; a hook blocks their edits outside the box, and the map marks the boxes they change as they go. Click *Review changes* when they are done. No agent open? *Run here* starts Claude Code headless: small, self-contained tasks build at once, anything that crosses roles plans first, and if it needs another file it stops and asks, and you allow the file, the whole role, or nothing.

**4. Review the run.** The boxes it changed turn green, the ones using changed code pale yellow, and a line above the map names them. The panel lists the changed functions, the tests it ran, a drafted commit message, and a revert.

## What is built in

Each feature serves one of the [golden rules](docs/GOLDEN_RULES.md) the project is designed against.

| | Feature |
|---|---|
| **Map** | Functions → roles → parts, at most 7 boxes on the first level. Copies of the same code are kept together, so a platform copy of your backend is the same function. Boxes with no link are listed apart, not drawn as vertices. |
| **Links with evidence** | Imports with file:line receipts, HTTP calls matched to route decorators, copied code, and co-change from git. |
| **Fence** | A Claude Code hook blocks edits outside the box; sealed runs also hide other modules' code and pass a compact brief of their interfaces instead. While a fence is set, agents you start yourself (Claude Code, Cursor, Copilot, Codex) are fenced too. |
| **Your own agent** | *Hand to my agent* fences the box for every agent in the project and copies the task; *Review changes* turns whatever it did into a run with changed functions, tests, commit message and revert. *Copy brief for agents* gives a box's interfaces, and the whole map as about 1.5k tokens of text, for any agent. |
| **Ask before crossing** | Out-of-fence needs become approval cards; approving continues the same conversation. |
| **Fewer tokens** | Fast path or plan-first per task, a three-sentence lean rule in every edit run, pointers to the project's own docs instead of their text. |
| **Tests** | The tests covering the fence and its users run before the agent may stop; branching logic added without a test is sent back once. |
| **History** | Every run is a version: the prompt, changed functions per box, tests, cost, diff, revert, and the names other modules used whose signature changed. |
| **Project knowledge** | Your markdown docs are placed on the roles they describe; a lesson from a run goes into a doc's *Gotchas* in one click. |
| **Skills for this project** | Skills from skills.sh matched to the libraries your code actually imports, added to this project only, on a click. |

Details: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## Measured, not claimed

All numbers come from scripts in [`bench/`](bench/) and are written up in [docs/EVALUATION.md](docs/EVALUATION.md), including the ones that showed no gain.

| Question | Result |
|---|---|
| Does fencing the right modules make cross-module features cheaper? | 4 features, all built correctly, 21% lower cost and 27% less time than handing the whole task to Claude Code (n = 2 each). |
| Does naming the module save tokens? | 19% lower cost on 4 rich tasks (16 runs per arm). |
| Does sealing save tokens on small tasks? | No: about 5% more; it is on for safety. |
| Does the lean rule save tokens? | Output tokens −9%, cost unchanged on small tasks (12 runs per arm). |
| Can an agent use the compact brief? | 88/88 questions answered from it. |
| Do the contract checks raise real alarms? | 8/8 flags on three git histories were real interface changes. |
| Which grouping keeps real changes inside one box? | Compared on five git histories; the shipped one never produces one-file crumbs. |

## Limits

- **Python only** for the map; other languages are not analyzed yet.
- **Claude Code runs the agent.** Other agents are fenced through the same hook while a fence is set, but only their payload shapes are tested.
- **The hook sees file tools, not shell commands.** A script can still write outside the fence; modfence reports it after the run and offers a revert.
- **Function names come from a model** and are a proposal: rename, regroup, or move roles.
- **No user study yet.** Whether the map makes people faster is not measured. That is where you come in.

## Help test it

modfence is young and needs people using it on real projects. If you try it:

1. Run it on a project you know well and give the agent one real task.
2. Open a [field report](https://github.com/ruijiezh67/modfence/issues/new?template=field-report.yml): how big the project is, whether the functions made sense, what the agent did, what confused you.
3. Bugs and ideas: [issues](https://github.com/ruijiezh67/modfence/issues).

**Privacy.** modfence runs on `127.0.0.1` only, has no telemetry, and sends nothing anywhere by itself. Code reaches a model only through your own Claude Code runs. Its state lives in `<project>/.modfence/`, git-ignored. See [SECURITY.md](SECURITY.md).

## Develop

```bash
git clone https://github.com/ruijiezh67/modfence && cd modfence
python -m unittest discover -s tests -t .
python -m modfence examples/*
```

The tests call no model: `tests/fake_claude.py` stands in for the CLI. Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [golden rules](docs/GOLDEN_RULES.md) before a change; every change names the rule it serves.

## License

MIT. See [LICENSE](LICENSE).
