# Evaluation

Three questions, each with its own experiment (section 9 adds a fourth: does the fence save tokens and time?). All numbers below come from the result files in [`bench/results/`](../bench/results/); anything not measured is written N/A.

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

**Since then.** Big graphs fold into folders and, above 12 modules, open at their roles (section 4). Imports now also resolve from a subfolder that the code runs from (`backend/` on `sys.path`): pydantic gains 64 edges (675 to 739), rich 7, fastapi none, and a private 581-file system went from 261 to 1,159.

## 4. Grouping files into roles

The top level of modfence is a project's roles (in a perception system: observer, segmenter, inference, memory ...). Roles rarely match folders, so modfence proposes them and the user renames, moves files and confirms. Which proposal method to ship was decided by measurement (2026-11-07, `bench/roles_eval.py`).

**Metrics.** Against a reference: ARI (adjusted Rand index; 1 = same grouping, about 0 = chance), NMI, and pairwise F1, the measures architecture-recovery papers report. MoJoFM, the field's third usual metric, is not implemented (N/A). Without a reference: Bunch's MQ per group (cohesion against coupling, higher is better), the share of import lines that cross groups (lower is better), groups caught in a dependency cycle (the Acyclic Dependencies Principle), and stability (ARI between the grouping of all files and of a random 90% of them, mean of 5 seeds).

**Reference.** One private research system: 581 Python files, 242k lines, a FastAPI backend with an older and a newer implementation of the same pipeline. A separate agent built the reference from the system's own architecture docs only, before any method ran and without seeing their output: 207 backend files in 16 roles, 134 placed because a doc names the file, 70 by folder rules the docs state, 3 confirmed by docstring; 17 files the docs do not place and 113 tests are not scored. Weaknesses: one annotator, partly stale docs, and 34% of placements follow folders, which favours folder methods.

**Deterministic methods** (selected rows; all rows in the private run notes):

| Method | Groups | ARI | NMI | F1 | MQ | Crossing imports | Cyclic groups | Stability |
|---|---|---|---|---|---|---|---|---|
| modfence modules (folders, flat folders split into files) | 383 | 0.06 | 0.66 | 0.07 | 0.01 | 0.96 | 66 | 1.00 |
| top folder | 44 | 0.22 | 0.61 | 0.31 | 0.20 | 0.35 | 19 | 1.00 |
| two folder levels | 54 | **0.42** | **0.71** | **0.46** | 0.25 | 0.37 | 23 | 1.00 |
| path words | 87 | 0.17 | 0.62 | 0.20 | 0.10 | 0.86 | 63 | 0.93 |
| Louvain on imports, hubs set aside | 24 | 0.18 | 0.46 | 0.28 | 0.66 | 0.06 | 6 | 0.91 |
| imports + folders + words (best of 6 weightings) | 19 | 0.26 | 0.52 | 0.33 | 0.76 | 0.14 | 10 | 0.84 |
| folders merged by imports | 18 | 0.22 | 0.48 | 0.33 | 0.58 | 0.07 | 2 | 0.89 |
| two folder levels, flat folders split by path words | 228 | 0.14 | 0.68 | 0.16 | 0.06 | 0.88 | 94 | 0.92 |

The structural metrics and the reference disagree: clustering the import graph gives the cleanest structure (crossing imports 0.06 against 0.37, few cycles) but matches the documented roles worst. The same split showed on fastapi, pydantic and rich, where no reference exists: import clustering cut crossing imports from 0.67-1.00 (folders) to 0.09-0.21 and removed most cycles, at stability 0.59-0.93 against 1.00 for folders. This agrees with the literature: documented architectures follow folders more than coupling.

**Adding a model.** One Haiku call names the groups. Asked freely to name groups, it merged same-job groups in 1 run of 3 (ARI 0.42 → 0.52 once, unchanged twice), so free naming was dropped. The shipped prompt is deductive: decide 6-15 roles from the project's own vocabulary, then assign every group to one; file moves need import evidence that code checks.

| Base grouping | Model | Runs | ARI | NMI | F1 | Run-to-run ARI | Cost per run |
|---|---|---|---|---|---|---|---|
| two folder levels | Haiku | 3 | 0.56 (0.53-0.58) | 0.71 | 0.60 | 0.87 | $0.004-0.008 |
| two folder levels | Sonnet | 1 | 0.56 | 0.69 | 0.61 | N/A | $0.088 |
| imports + folders + words | Haiku | 3 | 0.26 | 0.51 | 0.33 | N/A | $0.004-0.008 |
| **flat folders split by path words** | **Haiku** | 3 | **0.61 (0.54-0.66)** | **0.74** | **0.65** | 0.77 | $0.009-0.015 |

modfence ships the last row: from 0.42 (best deterministic) to 0.61 ARI for about one cent, and Sonnet at ten times the cost was no better. For scale only, since the systems differ: the best 2026 architecture-recovery method reports ARI 0.51 on eight other systems. Limits: one reference system, one annotator, three runs per row, and the model reads the same docs the reference was built from, which favours it. That is why the result is a proposal the user confirms, not an answer.

## 5. The AI-only brief, sealed runs and contracts (golden rules 4, 5 and 7)

Measured 2026-11-08. Raw rows: `bench/results/brief_probe_haiku.jsonl`, `bench/results/token_bench_round*.jsonl`.

**Can a model read the brief?** `bench/brief_probe.py` asks questions whose answers come from the code itself: the parameters of a function the fence uses, who uses a fence name, and whether a name is used (half are distractors). The model sees one encoding of the brief at a time. Setup: 7 fences (four examples, three rich modules), Haiku, $0.02 in total.

| Encoding | Size (tokens, chars/4) | Parameters | Users | Used or not | All |
|---|---|---|---|---|---|
| readable stubs (`sig`) | 145-1,468 | 20/20 | 17/20 | 45/48 | 82/88 |
| **compressed ids (`ids`, shipped)** | 41-1,280 | 20/20 | 20/20 | 48/48 | **88/88** |
| names only (`iface`) | 23-224 | 0/20 | 0/20 | 39/48 | 39/88 |

A first run of the probe caught a misleading header in the readable form ("what they offer" rather than "what the fence uses"), which is fixed above. Haiku is a lower bound for the agents that read the brief in practice.

**Does a sealed run save tokens?** `bench/token_bench.py` runs four tasks on rich (100 files, 26k lines; tasks and hidden acceptance tests in `bench/token_tasks.py`, checked to fail on rich as is and to pass with a reference solution). Agent: Claude Code with Opus 5.5.

Round 1 (2 runs per task and arm):

| Arm | Cost per task, median | Turns, median | Tokens billed, median | Acceptance | Reads of other modules |
|---|---|---|---|---|---|
| plain Claude Code, told the module | $0.243 | 5.5 | 189k | 8/8 | 0 |
| sealed modfence | $0.335 (+38%) | 11.5 | 374k | 8/8 | 0 (blocked: N/A, none tried) |

The seal did not save tokens here, and the round shows why. Told the module, Opus read only that file in every run, so there was no exploration to cut. The extra turns came from the harness. Its note fenced the tests and said the agent "may read and edit them", so the agent wrote tests nobody asked for. It also did not say that `python -c` and `cat >>` are blocked in a sealed run, so the agent retried. Round 2 fixes both, fences the module only, and adds a `vibe` arm (the task alone, no module named).

Round 2: 4 runs per task and arm, 16 per arm. Two copies of the run were started by mistake; both are kept, since each attempt is independent.

| Arm | Cost, sum of 16 | Cost per task, median | Turns, median | Tokens billed, median | Acceptance | Reads of other modules |
|---|---|---|---|---|---|---|
| `vibe`: Claude Code, task only | $5.12 | $0.284 | 9 | 309k | 16/16 | 0 |
| `plain`: Claude Code, told the module | $4.15 (-19%) | $0.247 | 6 | 191k | 16/16 | 0 |
| `sealed`: modfence | $4.38 (-14%) | $0.267 | 7 | 242k | 16/16 | 0 |

Median cost and tokens per task, in the order vibe / plain / sealed:
- T1 text.count: $0.317 / $0.237 / $0.254 (442k / 224k / 255k tokens);
- T2 table.add_rows: $0.255 / $0.244 / $0.273;
- T3 Panel.from_markup: $0.252 / $0.250 / $0.258;
- T4 filesize.parse: $0.440 / $0.300 / $0.302 (380k / 179k / 221k).

What this shows, and what it does not:
- **Naming the module saves the tokens.** It cut cost by 19% against asking with the task alone, and by up to a third on T4, where the agent otherwise wrote and debugged more. In modfence, picking the box is that act, so this saving is the module step's, not the seal's.
- **The seal costs about 5% on top**, and buys no evidence of benefit on these tasks. The brief adds about 2k prompt tokens (cache-creation median 24.4k against 22.5k), and one turn on the median. 6 of 16 sealed runs tried a blocked command once. No run in any arm read another module, so there was nothing to stop.
- **These tasks are small and fully specified.** Each names its class and needs at most one neighbour. Whether the seal pays off where an agent explores (vague requests, wide modules, a real research codebase) is N/A until measured. Golden rule 4 keeps the seal on by default anyway: it is the protection of working code, not a token saving.
- Spend for this section: $19.29 in model calls (pilot $0.58, round 1 $5.05, round 2 $13.64, probes about $0.04). This is over the $15 planned, because of the duplicate round-2 run.

**Did a run break what other modules use?** `bench/contract_replay.py` replays a git history at zero model cost. For each commit it checks every name another module used at the parent commit. Each flag was read against its commit by hand.

| History (last commits) | Commits with Python changes | Flags, first detector | Flags, final detector | Real contract changes among final flags |
|---|---|---|---|---|
| modfence | 14 | 2 (12 commits then) | 3 | 3/3 (a removal, two changed defaults) |
| requests (300) | 131 | 10 | 1 | 1/1 (`is_urllib3_2` removed; users updated in the same commit) |
| rich (300) | 191 | 5 | 4 | 4/4 |

The first detector's false alarms had three causes, each now a regression test:
- a base made generic or renamed by import (`MutableMapping` to `MutableMapping[str, T]`, `cookielib.CookieJar` to `CookieJar`, `List[T]` to `list[T]`);
- annotations on a plain class read as constructor parameters (only dataclass-like classes have field parameters);
- names defined under `if TYPE_CHECKING:` or `try:` missed.

The real flags on rich include a moved class (`CellTable`, 23 user files), a changed parameter (`cell_len(text, _cell_len)` to `cell_len(text, unicode_version)`), a reverted column class, and a renamed NamedTuple field (`before` to `style_before`).

Recall, that is breaks the check misses, is N/A: it needs labelled breaks, which these histories do not have. Known blind spots: uses through `getattr` or re-exported facades, and behaviour changes that keep the signature.

## 6. Building the first level: which grouping fits vibe coding (golden rules 2, 3 and 4)

The first level holds at most 7 areas; you pick one, then a role in it, and fence it. A grouping is good for that when a real change fits one area (one fence covers it) and areas are small (a tight fence). `bench/area_bench.py` measures both on each project's own git history, at zero model cost except the model row:

- **one area**: share of held-out commits whose files all lie in one area;
- **cover**: mean share of the code inside the areas a commit touches (lower is tighter);
- **largest**: share of the code in the biggest area.

Units are roles: a private project's 14 model-named roles, and for public projects the deterministic `roles.DEFAULT` groups (62 to 166 units, no model). Entry points, doors and shared config are left out as on the map. The newest 30% of commits are held out; co-change methods learn only from the older 70%. A commit counts if it changes 1 to 30 unit files. Only commits touching 2 or more units are scored: in a first run that also scored one-unit commits, random groupings did as well as most methods, because a one-unit change fits any grouping. Random rows are the mean of 20 seeds. Repositories at: celery `3a109cc`, rich `1a48583d4`, scrapy `2aefa609`, textual `5e5b7ef58`.

Cells are one area / cover / largest. Scored commits: private 52, celery 393, rich 65, scrapy 386, textual 630.

| Grouping (at most 7 areas) | private | celery | rich | scrapy | textual |
|---|---|---|---|---|---|
| random (floor) | .09 / .49 / .36 | .10 / .41 / .26 | .10 / .38 / .32 | .06 / .49 / .31 | .08 / .44 / .29 |
| top folders | .04 / .47 / .36 | .32 / .42 / .35 | .80 / .55 / .53 | .11 / .45 / .27 | .27 / .36 / .28 |
| imports, Louvain | .06 / .41 / .25 | .93 / .96 / **.96** | .18 / .38 / .33 | .20 / .58 / .45 | .13 / .50 / .45 |
| co-change only | .06 / .52 / .44 | .82 / .91 / **.91** | .83 / .83 / **.82** | .92 / .95 / **.95** | 1.00 / .98 / **.98** |
| co-change + imports + folders, no cap | .12 / .46 / .42 | .48 / .57 / .40 | .91 / .69 / **.74** | .52 / .74 / **.62** | .95 / .47 / .55 |
| **co-change + imports + folders, areas capped at 40% (shipped)** | .15 / .45 / .30 | .44 / .48 / .39 | .60 / .51 / .40 | .22 / .60 / .36 | .30 / .40 / .33 |
| imports + folders + file names, capped at 40% | .13 / .45 / .30 | .32 / .53 / .34 | .57 / .47 / .36 | .19 / .57 / .30 | .40 / .36 / .29 |
| a model (Sonnet) grouping, the shipped grouping as evidence | .15 / .45 / .30 | .18 / .34 / .32 | .38 / .30 / .24 | .22 / .60 / .36 | .30 / .40 / .33 |

What this says:
- **Uncapped methods cheat with a blob.** Co-change alone and imports alone often make one area of 80 to 98% of the code: every change then fits "one area", and the fence covers almost everything. The bold cells mark these. So areas are capped at 40% of the code.
- **Capped, the combined signal beats folders on 4 of 5 projects** (one-area share .15 vs .04, .44 vs .32, .22 vs .11, .30 vs .27) at a somewhat larger cover; on rich, where most code sits in one folder, folders win (.80 vs .60). Folders are one input, not the rule.
- **The model adds little.** Given the shipped grouping as evidence, Sonnet returned the same areas on 3 of 5 projects; on celery and rich its areas were tighter (cover .34, .30) but fitted fewer changes. Cost $0.02 to $0.05 per project. With weaker evidence (Louvain imports) it copied that too, and on celery (71 units) it once returned an invalid grouping, which `roles.apply_areas` rejects (the shipped fallback is the deterministic grouping).
- **A first level is a signpost, not a fence.** Even the best capped grouping fits only 15 to 60% of the changes that cross roles into one of 7 areas. The fence you set is usually a role or a part; an area is where you look first.

Limits: one held-out split per project; public units are deterministic groups, not model-named roles; whether people find these areas easier to pick from is N/A (no user study).

## 7. Building roles: the level you fence (golden rules 2 and 4)

A role is good to fence when a change that touches several files stays inside it. `bench/role_bench.py` scores each way of grouping files on the same five histories (newest 30% held out; commits that change 2 to 30 code files, entry points, doors and shared config left out). Methods make different numbers and sizes of groups, and small groups fit fewer changes by chance alone, so each is compared with its own floor: the same files shuffled among groups of the same sizes, 20 seeds. **Lift** = one-role share minus that floor. **Crumbs** = groups under 2% of the files, which become useless one-file boxes on the map.

Cells are lift (crumbs). Scored commits: private 76, celery 454, rich 65, scrapy 449, textual 739.

| Grouping | private | celery | rich | scrapy | textual |
|---|---|---|---|---|---|
| the private project's earlier roles: folder and path-word groups, then a model mapped them onto 14 named roles | .29 | N/A | N/A | N/A | N/A |
| folders, 2 levels (`folder`) | .65 (25) | .18 (18) | -.04 (79) | .15 (30) | .79 (6) |
| imports, Louvain (`imports`) | .60 (13) | .09 (12) | .14 (14) | .20 (9) | .17 (10) |
| imports + folders + path words (`hybrid`) | .60 (4) | .13 (5) | .14 (2) | .20 (2) | .18 (7) |
| folder and path-word groups merged to 15 by co-change, imports and folders, no role over 25% | .66 (6) | .27 (7) | .23 (7) | .19 (7) | .25 (9) |
| **the same, crumbs merged first (`history`, shipped)** | .67 (0) | .20 (0) | .08 (0) | .15 (0) | .23 (0) |

What this says:
- **Letting a model regroup roles cost fence locality.** On the private project, the model-mapped roles kept multi-file changes together far less often than deterministic groups of the same count (.29 against .60 to .67). So roles are now grouped by code and history, and the model only names them (`roles.propose_and_store`, about $0.005 with Haiku-class pricing on that project).
- **Change history is the strongest single signal** once groups are capped: the co-change rows lead on 4 of 5 projects. Uncapped co-change merging (not shown; see the bench) made 4 to 7 roles holding up to 63% of the files.
- **Merging crumbs first costs some lift** (rich .23 to .08, celery .27 to .20) but leaves no one-file boxes; a map of crumbs is not usable, so the shipped method pays that. On the private project the top-folder term in the similarity removed 7 crumbs (lift .70 to .67).
- Folders alone swing from best (textual, .79, but one folder holds 42% of the code) to below chance (rich, -.04): a hint, not a rule.

**Then the user chose function granularity anyway.** A first level of observer, inference, memory and so on is what people think in (golden rule 3), and those jobs span folders, which the deterministic signals only approximate: the shipped first level is now functions sorted by a model from blocks code cuts (copies always joined), with roles grouped by history inside each function. On the private project that gives 7 functions and 40 roles with lift .30 (21 crumbs, cover .10); these roles used the whole history, so the number is optimistic. That is the measured price of the granularity people asked for, against .67 for history-only roles (15 roles, cover .14). Cost of one proposal there: $0.18 (the function call with Sonnet $0.17).

Limits: one split per project; 65 to 739 scored commits; the earlier-roles row exists only where such roles were stored; whether people find these roles easier to pick from is N/A.

## 8. The lean rule (golden rule 7, built in)

Every edit run now carries `runner.LEAN_RULE`, three sentences in the spirit of the ponytail skill: the smallest change that does the task, reuse what the fence and brief have, no new dependency, file, option or abstraction, no code restated in the answer. Measured with `bench/token_bench.py --only sealed,lean` on the four rich tasks, 3 runs each, Claude Code with its default model, 2026-11-09 (`bench/results/token_bench_lean.jsonl`):

| Arm | Runs | Mean cost | Mean output tokens | Acceptance | Regression tests |
|---|---|---|---|---|---|
| sealed | 12 | $0.281 | 1,757 | 27/27 | 12/12 |
| sealed + lean rule | 12 | $0.278 | 1,596 | 27/27 | 12/12 |

Cost moved by 1% (within run-to-run noise at n = 12); output tokens fell 9%; nothing got worse. These tasks are small and fully specified, so there was little to over-build: the ponytail authors' 26% cost saving comes from a benchmark where agents tend to over-engineer. Whether the rule saves cost on open-ended or multi-file tasks here is N/A. It stays on because it costs about 60 tokens and measured no harm. Spend: $6.70.

## 9. Does the fence save tokens and time? (2026-11-09 to 11-11)

The core goal since 2026-11-10 (golden rule 6): the same coding goal for fewer tokens and less time. Five rounds on
real past fixes (the commit's parent, the commit's own tests or its files as the check), `claude -p`,
`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`. Means per run. The harnesses are in the author's local archive and not yet in
`bench/`; the private project's tasks are not published.

| Round | Project, model | Runs | Plain | Fenced | Check |
|---|---|---|---|---|---|
| A | a private Python project (about 400 files), Sonnet 5.5 | 4 tasks x 3 | $0.213 | sealed $0.252 (+18%), open $0.274 (+29%) | tests 9/12, 8/12, 8/12 |
| B (rich round 1) | rich, Sonnet 5.5, fence + note file | 5 x 3 | $0.114, 38 s | $0.176, 55 s | tests 15/15 vs 13/15 (one task fenced to the wrong module) |
| C (rich round 2) | rich, Sonnet 5.5, the fence line in the user's prompt | 5 x 3 x 4 arms | $0.194, 61 s | line + 3 likely places: $0.146 (-25%), 33 s (-46%) | tests 15/15 vs 14/15 |
| D (TinyDB) | TinyDB (4,900 lines), Haiku 5.5, the plugin, edit-only | 3 x 3 | $0.0079, 19.4 s | $0.0081 (+3%), 22.3 s (+15%) | diffs read by hand, all right after the fix below |
| E (rich round 3) | rich, Haiku 5.5, the plugin as shipped, edit-only | 5 x 3 | $0.0111, 32.1 s | $0.0114 (+3%), 36.6 s (+14%) | 15/15 edited the commit's files |
| F (rich round 3, again) | as E, with faster hooks and rarity-ranked pointers (28991a2), arms interleaved | 5 x 2 | $0.0109, 31.8 s | $0.0114 (+5%), 37.3 s (+17%) | 10/10 edited the commit's files |
| G (rich round 3, again) | as F, with every fix of 2026-11-11 (b5382a0), arms interleaved | 5 x 2 | $0.0116, 35.3 s | $0.0115 (-1%), 36.5 s (+3%) | 10/10 edited the commit's files |

Round C is the only saving, and plain cost 70% more in it than in round B, so it holds within that round only. Rounds
D, E and F, with the plugin as it ships (the fence picked from the task by a hook), saved nothing; in G, after the day's
fixes, it also cost nothing (-1% cost, +3% time), so the fence is now neutral on cost and is there to keep edits in scope; "edit-only" means no
Bash and nothing run, because running third-party code was not allowed in this environment (tests: N/A).

What the rounds did show:

- **A wrong fence costs the task.** The picker chose wrong in TinyDB (an "update operation" went to the table code
  whose functions are named update) and twice in rich (words about how to work, like "do not run the tests, only read
  and edit the code", moved the fence; a catch-all module outscored the right one 46 to 26). The right edit was denied
  and the task failed. Fixes: a module's own name and purpose count, plural s is stripped, such words are dropped, and
  a second module is fenced at half the first's score. Each is a regression test. Two more came from the ambiguity
  probe on TinyDB (section 10): "make the query cache bigger" is a class attribute (`default_query_cache_capacity`)
  that the picker did not score, and the fence denied the agent's own intent file under `.mod/intents/`, so it guessed
  instead of asking. Constants now score like functions and intent files are always writable.
- **No scope creep to stop, so far.** On rich r1, r4 and r5 with "tidy up anything else in the code base that looks off
  to you" appended (Haiku, no code-running tools, 6 runs per arm), plain edited outside the commit's module in 0 runs;
  the fenced arm in 1, inside its fence (the picker had added a second module). The fence's value against scope creep
  is not measured yet.
- **Hooks cost time on Windows:** about 0.6 s each (bash about 0.2 s, Python start about 0.3 s; the work itself 0.03 to
  0.16 s), 4 to 5 per task. `python -S` saves about 50 ms each.
- **A pointer can mislead.** The "likely start" listed functions that scored close to the right one, and the agent
  searched them (one extra turn); it is now ranked by word rarity (28991a2). In rich r1 the first module (styling, from
  the words "style" and "background") still sent the agent to style.py before console.py.
- **Fenced runs did more of the commit.** In r3 the fenced agent changed `_wrap.py`, `cells.py` and a test (the
  commit's own three files) in most runs; plain changed `_wrap.py` alone more often. Part of the extra cost is extra work.

## 10. Does stopping at a decision point save rework? (2026-11-11)

When a prompt leaves a setting open ("train it longer", "use a smaller learning rate", "make the training faster"),
the plugin's protocol has the agent write 2-3 readings and wait for a pick on the Intents page. Is that cheaper than
letting it guess and correcting it afterwards? Toy project (a config and a deterministic script written for the probe),
Haiku 5.5, a simulated person whose goal for each task was drawn once with `random.Random(7)` from plausible values
(epochs 40; lr 0.005; epochs 2). Plain arm: after a wrong result the person says "Not what I meant: I want KEY=VALUE"
in the same session. Mod arm: the person picks the reading that holds the goal, else writes it.

Reproduce: `python bench/rework_probe.py --runs 3` (it builds the toy in a temporary folder); results in
`bench/results/rework.jsonl` and `rework_rep2.jsonl` (28078d3: together 18 runs per arm, -40% cost, -8% time, 18 of 18
stopped, no correction) and `rework_40a0199.jsonl`. Three rounds, the first from the author's harness on
the same toy:

| Round | Arm | Runs | Right in the end | Corrections | Mean cost | Mean time |
|---|---|---|---|---|---|---|
| local (eae4edc) | plain | 9 | 9/9 | 9 | $0.0149 | 39.7 s |
| local (eae4edc) | with the plugin | 9 | 9/9 | 0 | $0.0088 (-41%) | 35.5 s (-11%) |
| `bench/` (40a0199) | plain | 9 | 9/9 | 8 | $0.0165 | 39.3 s |
| `bench/` (40a0199) | with the plugin | 9 | 9/9 | 0 | $0.0099 (-40%) | 37.2 s (-5%) |
| `bench/` (28078d3) | plain | 9 | 9/9 | 7 | $0.0157 | 39.4 s |
| `bench/` (28078d3) | with the plugin | 9 | 9/9 | 0 | $0.0104 (-33%) | 39.1 s |
| `bench/` (28078d3, repeat) | plain | 9 | 9/9 | 9 | $0.0181 | 43.4 s |
| `bench/` (28078d3, repeat) | with the plugin | 9 | 9/9 | 0 | $0.0100 (-45%) | 36.7 s |

Every plain first guess missed (epochs 50 or 100, lr 0.001, a guessed speed-up), so every plain run needed one
correction. The plugin's agent stopped in 9 of 9 runs and was right first time in all 9 (3 picks, 6 own words: no
reading held epochs 40 or 2). A plain run that guesses right costs $0.0066 to $0.0079, so stopping pays when the agent
would guess right less than about 73% to 76% of the time. The person's time on the page is not counted.

Reproduce the TinyDB part with `python bench/ambiguity_probe.py --repo PATH/tinydb --runs 3`. It now runs `claude -p
--restricted --strict-mcp-config` (no code-running tools, no user settings, no MCP servers), which roughly halves the cost
of both arms, so its numbers are not comparable with the table below (run with Bash disallowed instead). Its own round
(`bench/results/ambiguity.jsonl`, 504fa4f, 9 runs per arm): plain $0.0081, 16.2 s; with the plugin $0.0083 (+2%), 22.6 s
(+40%: runs are short, so the hooks' few seconds show), 1 stop, the same 6 corrections.

**On a real repository it did not pay.** Three one-constant requests on TinyDB ("make the query cache bigger", "use a
shorter name for the default table", "make the caching middleware write to disk more often"), goals drawn the same way
(100, 'default', 500), edit-only (no shell, so the agent writes its intent and ends its turn; the answer comes with
"continue"), 9 runs per arm:

| Plugin | Arm | Right in the end | Corrections | Stops | Mean cost | Mean time |
|---|---|---|---|---|---|---|
| 122ba4e | plain | 9/9 | 6 | N/A | $0.0150 | 26.7 s |
| 122ba4e | with the plugin | 9/9 | 6 | 3 | $0.0167 (+12%) | 37.7 s |
| 3dd16f7 | plain | 9/9 | 6 | N/A | $0.0155 | 27.0 s |
| 3dd16f7 | with the plugin | 9/9 | 4 | 4 | $0.0164 (+6%) | 36.6 s |
| 28078d3 | plain | 9/9 | 6 | N/A | $0.0150 | 27.5 s |
| 28078d3 | with the plugin | 9/9 | 6 | 0 | $0.0138 (-8%) | 31.2 s |
| 28078d3, repeat | plain | 9/9 | 6 | N/A | $0.0153 | 27.5 s |
| 28078d3, repeat | with the plugin | 9/9 | 5 | 0 | $0.0124 (-19%) | 28.6 s |

The agent stopped most where its guess was right (plain chose 100 for "bigger" every time) and least where it was
wrong. In the first round it also wrote its intent and edited the code anyway; since 3dd16f7 an open intent holds edits
until the answer, and every run that stopped then waited. So stopping pays on settings people want exactly (an
experiment's epochs or learning rate), and not, so far, on code constants where a sensible guess is often fine. Since
28078d3 the protocol says so ("for a code tweak where any sensible value would do: pick one and name it"): on TinyDB
the agent no longer stopped (-8%), and on the toy it still stopped every time (-33%). The
simulated person wants one exact value, which is harsher on guessing than most people.

How it got here: before 6eb826a ("longer, smaller, faster ... with no number leaves that setting open") the agent did
not stop on "use a smaller learning rate"; before eae4edc ("change nothing yet") it once removed the toy's sleep for
"make the training faster" and only then asked. An earlier round (-23%) is void for one task: the harness did not
restore the toy script, which an agent had edited. A `bench/` round before 40a0199 measured -30% with one wrong
answer: the reply said "use it verbatim: set epochs to 2" and also "Settings: epochs=10", and the agent set 5; the reply
now never sends a value the readings disagreed on.

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
