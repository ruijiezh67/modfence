# Golden rules

modfence exists for **module vibe coding**: the project is a few modules, you hand your agent one module at a time, and every round leaves a receipt of what it touched.

**The core goal: the same coding goal, done with fewer tokens and in less time.** Given one module instead of the whole project, Claude Code should reach the same working change with fewer turns, fewer tokens and less waiting than plain Claude Code. That is the number modfence is judged by (rule 6), and anything modfence adds to the agent's work (a note to read, a hook to run, a check to pass) is a cost against it.

A side goal, not the reason it exists: because an agent can change only the module it holds, several people, or several agents, can work on one codebase at once without breaking each other's work. `MODULES.md` is the agreement on who holds what. **For now modfence supports Claude Code only**; other agents (Codex, Cursor, Copilot) come once people use it, and nothing is built that would rule them out.

It serves two kinds of user, and every feature must work for at least one of them:

- **Engineers who live in the terminal** and run agents, often several at once or in loops. They get the fence and the receipt as a Claude Code plugin and a command line, with no page to open.
- **People who need to see the project first**: newcomers, reviewers, anyone taking over code they did not write. They get the map.

## One loop: see, steer, review, understand

modfence is one loop around every agent round, and every step exists in a working form before any step is polished:

| Step | What a person gets | Built as |
|---|---|---|
| **See** | the project as modules they can edit, which agents must obey | the map, `.mod/project.mod` (rules 1 to 3) |
| **Steer** | the task picks the module just in time; the agent stays inside it; crossing asks first | `modfence jit` and the fence hook in the plugin, `modfence fence` (rule 4) |
| **Review** | what each round, or each of many agents, touched, broke, and was blocked from | `modfence receipt`, `--fleet`, the Stop hook (rule 5) |
| **Understand** | a check that they still know what changed | `modfence quiz`, its score over rounds (rule 3) |

The map checks itself too: the receipt says when the modules name folders that are gone or miss new code.

**Not built here:** another loop or background agent runner (crowded, expensive, hard to verify), a general coding assistant or IDE (no measurable win), a generator of architecture diagrams (measured to cost more and go stale), tests of agents against deception (a separate project).

## What the field taught us

Five lessons from the people who run agents every day (posts on X, 2025-2026), from published studies and from our own measurements. The rules below follow from them.

1. **Review is the limit, not the agent.** "Your review bandwidth decides how many you can actually run, not the tool" (Addy Osmani). modfence makes review cheap: a change is read as modules, not as a diff.
2. **People still read the code that matters.** Karpathy kept vibe coding to "throwaway weekend projects"; Mitchell Hashimoto's planner, coder and judge loop ends with "I read the code". modfence keeps the person's understanding; it does not replace it.
3. **Verification beats instructions.** The most-liked tip in Boris Cherny's thread is "give Claude a way to verify its work". modfence's guarantees are hooks and checks, not prompt text.
4. **Tokens are turns times context, so only fewer turns save.** Handing the agent a map of the repository does not pay: ContextMesh (a small one-person project, 2026) reported +36% to +75% cost under prompt caching with no significant change in turns and success not measured, and an ETH Zurich study (arXiv 2602.11988) found model-written context files cost 20% to 23% more with no gain in success. Pointing at the exact place does pay: in our second rich round, one line naming the module plus three likely functions cost 25% less and took 46% less time than plain Claude Code (14 of 15 passing). Our own A/B on a lab project (36 runs, 4 real tasks) measured the fence at +18% to +29% cost, and on rich (30 runs, 5 tasks) at +54%: a well-specified task already sends the agent to the right files (2.3 files read, none outside the module), and each instruction in the fence note added turns (more test runs and checks). Where the task does not say where to work, the fence cut cost by 21%. So the fence saves only when it removes searching, and everything else it adds must cost nothing: a note the agent must open is a turn, and a hook that starts a Python process on every tool call is waiting (0.35 to 0.7 s each, now only on edits). The plugin as shipped (the fence picked from the task, Haiku, 2026-11-11) saved nothing on rich or TinyDB (+3% to +5% cost, +14% to +17% time), and a wrong pick cost the whole task until the picker was fixed.
5. **Agents that never stop overreach, and people approve stops without reading.** On OverEager-Bench (arXiv 2605.18583, about 7,500 runs) agents that run without asking acted outside the task in 5.4% to 27.7% of runs, against 0.2% to 4.5% for one that asks first, and removing the sentence that states the allowed scope took Claude Code from 0% to 17.1%. Yet people approve 93% to 97% of Claude Code's permission prompts, and in Michelle Lam's just-in-time objectives study users "were quick to confirm goals unless they were noticeably off-course". So the agent stops only at decision points, says exactly what it would otherwise guess, and nothing on the page leans toward one answer.
6. **Asking beats correcting, when the guess would be wrong.** On prompts that leave a value open ("train it longer"), stopping for a pick cost 41% less and took 11% less time than guessing and being corrected (Haiku, 18 runs, a simulated person; EVALUATION section 10), and it pays as long as the agent would guess right less than about 73% of the time. It only worked once the protocol named the pattern (a comparative with no number) and said "change nothing yet": without that, the agent guessed or acted first. This, not the fence, is where modfence has measured a saving so far.

The seven rules come in three groups. Each rule has a **Done when** line: a check that a reviewer, a test or a script can run. Where a rule names a target not built yet, **Next** says the first step. A change that serves no rule does not ship. A change that breaks one needs a written reason.

## A. Modules

**1. Modules are written down, edited by people and binding on agents.**
The modules live in `.mod/project.mod`, modfence's own file that replaces `MODULES.md` (a name, one line of purpose, folders and files per module; an old `MODULES.md` is read once). modfence proposes a first level of about 7 modules; that is a starting point, and people split, merge and add modules as the project needs. People edit the modules on the page, never in the file; agents are bound by them through the fence and read them in the session context. It is never a one-off diagram an agent drew. `.mod/` stays out of git unless the person shares it, and then a team shares one picture of who holds what. modfence writes it only when the user saves the map or the page. Test files belong to no module: everyone may run and extend them.
*Done when:* every feature that needs module membership reads the project's `.mod`, and a file no module claims is shown as unassigned, not guessed.

**2. Structure is computed, not guessed.**
Imports, git history, copies and runtime links decide the structure, and the analysis learns what it can from the project itself (for example the folders a program puts on its import path). A model may name and summarize, never decide on its own. A weak signal (one commit that touched two modules) never stands in for a missing strong one. Prefer proven open-source methods to new ones.
*Done when:* the structure can be rebuilt with no model call, every model call shows its token cost, and every link on the map shows the evidence it rests on.

**3. People see modules, and keep understanding them.**
The map shows the modules, links that say what they mean, and what the last round changed. Inside a module, one level of parts is allowed if it makes the module easier to read. There are no function-level graphs and no decoration.
*Done when:* someone who did not watch the round can tell, from the map and the receipt alone and in under a minute, which modules changed and what that may break.
`modfence quiz` asks those questions after a round, from the receipt, and keeps the score.
*Next:* measure it (rule 6): the quiz score after rounds with and without modfence, and whether a person can redraw the modules from memory.

## B. Agents

**4. The fence is a hook, granted per module, and costs no turns or time.**
While a fence is set, a hook blocks any edit outside the fenced module. The fence is set just in time: when you give the agent a task, modfence picks the module the task names in the code and shows you the guess, the functions behind it and the other candidates, so you can notice a wrong guess and switch in one click (Michelle Lam's just-in-time objectives, CHI 2026; Elena Glassman's point that people must be able to notice and judge an AI's choice). A fence a person sets from the map or the terminal is kept, and crossing into another module needs that person's approval. The fence must not cost the agent turns or time: hiding other modules' code ("sealed") made agents hit the hook about twice a run for no measured gain, so it is off unless a measurement shows it pays; the hook runs only on the tools that edit. As a side benefit, two agents in two worktrees can hold two modules at once.
Where the agent would have to guess (lesson 5: a short request that leaves settings open, an experiment's configuration, a run, results going into docs, something hard to undo, a fence crossing, the same test failing twice), it writes what it understood into an intent `.mod`: the person's words, two or three distinct readings with evidence, and each setting with its source (said, default, remembered with its date, guessed). The page shows only what needs judging (guesses and memory first, readings side by side by their differences, shuffled, none preselected or recommended); one key continues, and the waiting agent goes on at once. A confirmed setting is written to the project and never asked again. Each stop is a cost: a task should stop at most twice.
*Done when:* a test shows the hook denying an outside edit by Claude Code and starting only on edit tools, two fences set in two worktrees of one repository do not affect each other, and a probe shows an agent writing an intent for a vague request and changing nothing until the answer.

**5. Every round leaves a receipt, built for review.**
After a round, the receipt says which modules changed, which modules use them, which names other modules rely on were broken, which cross-module dependencies are new, which files are outside the fence, and which tests to run. It comes from git and static analysis, with no model. On a break it blocks the agent once, then lets it stop. It is shown on the map and in the terminal, and it reads in seconds, because review is the limit (lesson 1).
*Done when:* `modfence receipt` reports all of these and exits non-zero on a break, and the map highlights the changed boxes.
`modfence receipt --fleet` gives one receipt per worktree, so many agents are reviewed by module.
*Next:* the same on the map: the receipts of 10 to 100 parallel agents side by side, with each one's cost once it is known.

## C. Decisions

**6. Fewer tokens and less time for the same goal, measured.**
The core goal is checked by one A/B: the same task from a real project's history, plain Claude Code against Claude Code with the fence, at least 3 runs per arm, correctness checked by the commit's own tests. Cost is counted per outcome, as dollars per change that passed its tests, not per run; time is the agent's wall time. Every part of the fence is tested on its own (the line the person pastes, the note, a hint of where the code is), so a part that costs is found and cut. A value nobody measured is written N/A, never 0. The limits are published with the result. Beside tokens and time, the A/B counts the three failures it exists to prevent: files changed outside the task's module, stops per task (at most 2), and whether the person's meaning was among the readings shown. Until a round shows a saving, modfence does not claim one: so far the full fence note cost 18% to 54% more on well-specified tasks and 21% less on vague ones, and a one-line fence with likely places cost 25% less in one round that still needs repeating.
*Done when:* the latest A/B is in the docs with its runs, and every number in the docs links to the run that produced it.

**7. Complete first, then the least that works.**
Every step of the loop works end to end in a plain form before any step is made better: a crude piece that exists beats a polished piece that is missing. Each piece is the least that works: check whether the codebase, the standard library or Claude Code already does it, build it for the terminal first and draw it on the map second, and keep anything the agent reads from modfence (fence note, brief) as short as measurement allows.
*Done when:* every step in the loop table has a command that runs, and each change is the smallest diff that passes its check and adds no dependency.

## Using the rules

- A commit that changes behaviour names the rule it serves ("rule 5").
- A design names what it gains and what it costs on each rule it touches.
- When rules conflict, this order wins: **4** (working code stays safe), then **6** (the core goal, measured), then **5** (you know what changed), then the rest in number order.
