# Evaluation

Three questions, each with its own experiment. All numbers below come from the result files in [`bench/results/`](../bench/results/); anything not measured is written N/A.

1. **Does the fence keep an agent inside it?** And what does a fenced run cost compared with plain Claude Code and with Claude Code's own permission rules?
2. **Fence coding vs vibe coding.** Building a whole cross-module feature module by module (each run fenced to one module) versus just asking the model: how often is the feature right, and how many tokens does it take?
3. **Does the analyzer hold up on real, popular repositories**, including LLM-training code?

## Setup

| Item | Value |
|---|---|
| Agent | Claude Code 2.1.318, headless (`claude -p`), the account's default model. The model id was not recorded in the first two runs: N/A. Later runs record it (`model` in each step). |
| Isolation | Each attempt runs on a fresh copy of the example project. `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, so no user `CLAUDE.md` reaches the agent. Same allowed tools in every condition (`Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash(python:*)`, read-only `git`/`ls`/`cat`). |
| Machine | Windows 11, Python 3.13.5; up to 3 attempts in parallel. |
| Date | 2026-11-06 |

## 1. Staying inside the fence

**Tasks.** Task 4 of each of the first three examples. Each needs changes in 3–4 modules, but the fence allows one: `calc/evaluator` for the `^` operator, `library/services` for late fines, `sheet/functions` for string values and `CONCAT`. The prompt is the task's section of `TASKS.md` plus "Implement it and make the tests pass", which invites edits outside the fence.

**Conditions.**

| Condition | What the agent gets |
|---|---|
| plain | The task, plus "Only change files in `<module>/`. Do not edit any other file." Nothing enforces it. |
| native | The same prompt, plus Claude Code's own `permissions.deny` rules: `Edit(<module>/**)` for every other module. |
| modfence | The task only. modfence's system note (the module, its files and public names, what it depends on and what uses it) and its `PreToolUse` hook. |

**Results** (2 runs per task and condition, 6 per condition; [`fence-2026-11-06.jsonl`](../bench/results/fence-2026-11-06.jsonl)):

| Condition | Runs with edits outside the fence | Edits blocked | Project tests pass | Cost per run, mean ± sd | Turns per run, mean ± sd |
|---|---|---|---|---|---|
| plain | 0/6 | 0 | 6/6 | $0.408 ± 0.081 | 13.7 ± 6.8 |
| native | 0/6 | 0 | 6/6 | $0.341 ± 0.057 | 8.3 ± 3.6 |
| modfence | 0/6 | 1 | 6/6 | $0.353 ± 0.115 | 6.8 ± 3.7 |

**What this shows.**
- With this model, an instruction alone was enough: no condition edited outside the fence. The fence did not make a difference to compliance here; it is a guarantee, not a measured improvement. The one blocked edit (modfence, library, second run) is the case the hook exists for: the agent did try, and the edit did not happen.
- modfence runs took about half the turns of plain runs (6.8 vs 13.7). The cost difference ($0.353 vs $0.408) is within one standard deviation at n = 6, so it is not established.
- Every run in every condition named the modules that still needed changes (the `named_modules` field), so the hand-off text was there in all three.
- Not measured: edits through shell commands (`python -c` writing files) are reported by modfence after the run, not blocked; this experiment saw none.

## 2. Fence coding vs vibe coding

**Question.** Is it cheaper or more reliable to build a cross-module feature in fenced, module-sized steps than to hand the whole task to the model?

**Tasks.** Task 4 of all four examples, including the PyTorch one (`04-tinygpt`: gradient accumulation and clipping, across `config` and `train`).

**Conditions** ([`bench/feature_bench.py`](../bench/feature_bench.py)):

| Condition | Runs per attempt | What happens |
|---|---|---|
| vibe | 1 | The task text only. No module map, no fence. |
| fence-all | 1 | One modfence run fencing every module the task needs (tests not fenced). |
| fence-all-tests | 1 | The same plus the tests module: the fence an exercise sets up in the UI. Run separately, after the bug below was found. |
| fence-chain | 2–4 | One modfence run per module, foundations first. Each run is told its step number, what earlier steps did and what later steps will do. |

**Correctness** is judged by [`bench/acceptance.py`](../bench/acceptance.py), not by the agent. It has one black-box check per bullet of the task's Acceptance list in `TASKS.md`, 20 checks in all, run through the project's own CLI (or, for tinygpt, a short script that trains with fixed seeds). On the untouched examples all 20 checks fail; three checks that passed on the untouched code in a first draft were tightened so they only pass when the feature works.

**Results** (4 tasks × 2 attempts = 8 per condition; [`feature-2026-11-06.jsonl`](../bench/results/feature-2026-11-06.jsonl), [`feature-tests-2026-11-06.jsonl`](../bench/results/feature-tests-2026-11-06.jsonl); tables from `bench/summarize.py`):

| Condition | Features fully correct | Project tests pass | Runs | Cost per feature, mean ± sd | Turns | Context tokens read from cache | Output tokens | Wall time |
|---|---|---|---|---|---|---|---|---|
| vibe | 8/8 | 8/8 | 1 | $0.71 ± 0.25 | 30.4 | 726,926 | 11,156 | 172 s |
| fence-all | 8/8 | 2/8 | 1 | $0.54 ± 0.18 | 20.5 | 519,023 | 7,464 | 125 s |
| fence-all-tests | 8/8 | 8/8 | 1 | $0.56 ± 0.19 | 20.5 | 457,671 | 8,066 | 126 s |
| fence-chain | 8/8 | 2/8 | 3.2 | $1.08 ± 0.43 | 34.6 | 843,091 | 9,966 | 204 s |

Token and time columns are means per feature. Cost per task (mean of 2):

| Task | vibe | fence-all-tests | fence-chain |
|---|---|---|---|
| calculator `^` (3 modules) | $0.56 | $0.51 | $0.90 |
| library fines (4 modules) | $0.61 | $0.51 | $1.33 |
| spreadsheet text + CONCAT (4 modules) | $1.11 | $0.84 | $1.56 |
| tinygpt grad accumulation (2 modules) | $0.57 | $0.37 | $0.53 |

**What this shows.**
- **Everything was built correctly.** All 32 attempts passed every acceptance check. These tasks did not separate the conditions on correctness; harder tasks are needed for that.
- **Fencing the modules a feature needs is cheaper than just asking.** With the exercise-style fence (fence-all-tests), cost per feature was 21% lower than vibe ($0.56 vs $0.71), context re-read 37% lower, output 28% lower and wall time 27% lower, with all project tests passing. It was cheaper on each of the 4 tasks (one-sided sign test over tasks: p = 0.0625, so suggestive, not established). The likely reason: the system note hands the agent the module map (files, public names, who imports what), so it explores less: 20.5 turns against 30.4.
- **One module per run costs more, not less.** fence-chain cost 52% more than vibe. Each step is a new session that re-reads the project. Its value is smaller, reviewable steps (each run's diff touches one module), not tokens.
- **Leaving the tests outside the fence left stale tests.** fence-all and fence-chain built correct features, but 6/8 left one old test failing, because the test that encoded the old behavior could not be updated from inside the fence. Since this run, an exercise fences the tests module too (fence-all-tests: 8/8 tests pass).

**Bugs found in the benchmark itself.** One library check ("returning on the due date gives a fine of 0.00") reused a member who already owed 12.50 from the earlier checks, so lending was correctly refused and the check failed every implementation. It is excluded from the first results file (`summarize.py --exclude "02-library:return 0 days late prints fine 0.00"`, so library counts 5 checks there) and fixed for the fence-all-tests run (6 checks, all passed).

**Limits.** n = 2 per task and condition; one model; tasks and checks written by the modfence author; small, cleanly layered projects; the account's default model was not recorded (N/A).

### First look at plan and build (n = 1, not a benchmark)

Plan and build were added after the runs above. One real run on a fresh copy of the calculator, fence = lexer, parser, evaluator and tests, request = the `^` operator (2026-11-07, Claude Code 2.1.319, account default model):

| Step | Cost | Turns | Result |
|---|---|---|---|
| plan (read only) | $0.244 | 5 | 2 questions with recommendations; 8 functions and classes to touch |
| build (resumes the plan session) | $0.512 | 19 | done check passed first time (24 tests); 16 units added or changed across 7 files |
| total | $0.756 | 24 | |

For comparison only: fence-all-tests on the same task cost $0.51 (mean of 2) without a plan step. This single run cost 48% more, but the prompt differed (no acceptance list) and n = 1, so it says nothing yet about whether the plan step pays for itself. Two things it did show: the build agent spent 4 tool calls trying to run the tests with commands the run did not allow, while the done check had already run them; build runs are now told that the done check runs the tests. And the planner answered in the account's chat language (Chinese here), because runs keep the user's own Claude Code settings.

## 3. The analyzer on popular repositories

Shallow clones at the commits below, parsed as data (nothing in them is executed). Times are warm-cache, single process, on the machine above.

| Repository | Stars (GitHub API, 2026-11-06) | Commit | `.py` files | Lines | Modules | Import edges | Parse errors | Seconds |
|---|---|---|---|---|---|---|---|---|
| karpathy/nanoGPT | 64,512 | 3adf61e | 15 | 1,220 | 9 | 3 | 0 | 0.3 |
| karpathy/nanochat | 60,339 | 92d63d4 | 36 | 7,775 | 26 | 67 | 0 | 0.8 |
| psf/requests | 54,708 | 3c7baaa | 37 | 12,032 | 24 | 89 | 0 | 0.8 |
| encode/httpx | 15,742 | b5addb6 | 60 | 17,753 | 21 | 77 | 0 | 1.7 |
| pallets/flask | 75,055 | 49943b5 | 83 | 18,392 | 38 | 109 | 0 | 0.5 |
| Textualize/rich | 57,738 | 9d8f9a3 | 213 | 51,866 | 141 | 598 | 0 | 1.0 |
| fastapi/fastapi | 104,525 | 1ca09c1 | 1,219 | 131,859 | 430 | 664 | 0 | 4.8 |
| pydantic/pydantic | 29,343 | c9b9290 | 3,155 | 224,859 | 303 | 675 | 0 | 7.7 |

**What changed because of this test.**
- **Flat code is split into file modules.** Training repos keep `model.py` and `train.py` at the root, and nanochat keeps 15 files in one `nanochat/` package. With "a module is a directory", nanoGPT was one module and nanochat's core was one module, so nothing useful could be fenced. Now each root `.py` file, and each file in a directory with 8 or more `.py` files of its own, is a module: you can fence `nanochat/gpt.py` or `train.py` alone.
- **Import scanning visits statements only.** It was 60.7 s on pydantic; it is 7.7 s now, with identical imports found in all 3,451 files of flask, rich and pydantic (checked against the full `ast.walk` version).

**Not solved.** Big libraries now give big graphs (rich 141 modules, fastapi 430 because its `docs_src/` holds hundreds of example programs). There is no collapse or filter yet.

## How modfence compares with popular tools

Star counts are from the GitHub API on 2026-11-06. Feature cells come from each project's README and docs ([research notes](../../research_notes/Modmap%20next%20step%20priorities/competitor_tools.md)); N/A means not found in their docs.

| Tool | Stars | Module map from | Prompt from a module | Edit boundary enforced | Per-run diff, revert | Runs locally |
|---|---|---|---|---|---|---|
| modfence | private | `ast` imports, with file:line receipts | yes | yes: `PreToolUse` hook on file tools; shell writes reported, not blocked | yes | yes |
| Claude Code `permissions.deny` | (part of Claude Code) | none | no | yes, for the paths you list by hand | N/A (git) | yes |
| Aider-AI/aider | 49,990 | repo map (tree-sitter), text only | no | edits only files added to the chat; `/read-only` for context | git commits per change | yes |
| tirth8205/code-review-graph | 32,627 | tree-sitter graph, served over MCP | no click-to-prompt UI found | no | no | yes |
| ahmedkhaleel2004/gitdiagram | 18,779 | an LLM draws a Mermaid diagram | click opens the file | no | no | hosted; local run needs cloud services and an OpenAI or OpenRouter key |
| AlgoNoRhythm/Flare | 309 | regex/lexer import parser | yes | N/A | N/A | yes |

The popular tools either draw the map (GitDiagram, code-review-graph) or edit code (Aider, Claude Code); none found draws the map, lets you aim an agent at one part of it, and enforces and reviews that boundary in the same place.

## Self-made data

- **Tasks and acceptance checks.** The task texts and their Acceptance bullets in each `examples/*/TASKS.md` were written for these examples by the modfence author, before any benchmark run. `bench/acceptance.py` translates each bullet into one check, without reference to any agent's output. Fixed inputs: library dates start at 2026-01-05 with the project's own loan period; tinygpt checks train on `"abcd" * 64` with seed 0.
- **Training text.** `examples/04-tinygpt/data/tiny.txt`: 20 English lines written for the example (four are well-known pangrams), repeated 6 times, about 6 KB. It only makes a run finish in seconds with a falling loss; it says nothing about model quality.
- **How it differs from real work.** The examples are small (385–1,189 lines) and cleanly layered, with module boundaries drawn on purpose. Real projects have blurrier boundaries, so a per-module chain may need more hand-off text there.
