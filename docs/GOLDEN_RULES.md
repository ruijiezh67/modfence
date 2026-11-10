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
| **See** | the project as modules they can edit, which agents must obey | the map, `MODULES.md` (rules 1 to 3) |
| **Steer** | an agent kept inside one module; crossing asks first | the fence hook, `modfence fence`, the plugin (rule 4) |
| **Review** | what each round, or each of many agents, touched, broke, and was blocked from | `modfence receipt`, `--fleet`, the Stop hook (rule 5) |
| **Understand** | a check that they still know what changed | `modfence quiz`, its score over rounds (rule 3) |

The map checks itself too: the receipt says when `MODULES.md` names folders that are gone or misses new code.

**Not built here:** another loop or background agent runner (crowded, expensive, hard to verify), a general coding assistant or IDE (no measurable win), a generator of architecture diagrams (measured to cost more and go stale), tests of agents against deception (a separate project).

## What the field taught us

Four lessons from the people who run agents every day (posts on X, 2025-2026) and from our own measurements. The rules below follow from them.

1. **Review is the limit, not the agent.** "Your review bandwidth decides how many you can actually run, not the tool" (Addy Osmani). modfence makes review cheap: a change is read as modules, not as a diff.
2. **People still read the code that matters.** Karpathy kept vibe coding to "throwaway weekend projects"; Mitchell Hashimoto's planner, coder and judge loop ends with "I read the code". modfence keeps the person's understanding; it does not replace it.
3. **Verification beats instructions.** The most-liked tip in Boris Cherny's thread is "give Claude a way to verify its work". modfence's guarantees are hooks and checks, not prompt text.
4. **Tokens are turns times context, so only fewer turns save.** ContextMesh measured a repo map handed to the agent at +36% to +46% tokens with no turns saved. Our own A/B on a lab project (36 runs, 4 real tasks) measured the fence at +18% to +29% cost, and on rich (30 runs, 5 tasks) at +54%: a well-specified task already sends the agent to the right files (2.3 files read, none outside the module), and each instruction in the fence note added turns (more test runs and checks). Where the task does not say where to work, the fence cut cost by 21%. So the fence saves only when it removes searching, and everything else it adds must cost nothing: a note the agent must open is a turn, and a hook that starts a Python process on every tool call is waiting (0.35 to 0.7 s each, now only on edits).

The seven rules come in three groups. Each rule has a **Done when** line: a check that a reviewer, a test or a script can run. Where a rule names a target not built yet, **Next** says the first step. A change that serves no rule does not ship. A change that breaks one needs a written reason.

## A. Modules

**1. Modules are written down, edited by people and binding on agents.**
The modules live in `MODULES.md` at the repository root (a name, one line of purpose, folders and files). modfence proposes a first level of about 7 modules; that is a starting point, and people split, merge and add modules as the project needs. People edit the file, by hand or on the map; agents are bound by it through the fence. It is never a one-off diagram an agent drew. Every agent (it is plain Markdown that `CLAUDE.md` points to), hook and CI reads the same file, so a team shares one picture of who holds what. modfence writes it only when the user saves the map. Test files belong to no module: everyone may run and extend them.
*Done when:* every feature that needs module membership reads `MODULES.md` when it exists, and a file no module claims is shown as unassigned, not guessed.

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
While a fence is set, a hook blocks any edit outside the fenced module. A person grants and lifts a module for an agent from the map or from the terminal, and crossing into another module needs that person's approval. The fence must not cost the agent turns or time: hiding other modules' code ("sealed") made agents hit the hook about twice a run for no measured gain, so it is off unless a measurement shows it pays; the hook runs only on the tools that edit. As a side benefit, two agents in two worktrees can hold two modules at once.
*Done when:* a test shows the hook denying an outside edit by Claude Code and starting only on edit tools, and two fences set in two worktrees of one repository do not affect each other.

**5. Every round leaves a receipt, built for review.**
After a round, the receipt says which modules changed, which modules use them, which names other modules rely on were broken, which cross-module dependencies are new, which files are outside the fence, and which tests to run. It comes from git and static analysis, with no model. On a break it blocks the agent once, then lets it stop. It is shown on the map and in the terminal, and it reads in seconds, because review is the limit (lesson 1).
*Done when:* `modfence receipt` reports all of these and exits non-zero on a break, and the map highlights the changed boxes.
`modfence receipt --fleet` gives one receipt per worktree, so many agents are reviewed by module.
*Next:* the same on the map: the receipts of 10 to 100 parallel agents side by side, with each one's cost once it is known.

## C. Decisions

**6. Fewer tokens and less time for the same goal, measured.**
The core goal is checked by one A/B: the same task from a real project's history, plain Claude Code against Claude Code with the fence, at least 3 runs per arm, correctness checked by the commit's own tests. Cost is counted per outcome, as dollars per change that passed its tests, not per run; time is the agent's wall time. Every part of the fence is tested on its own (the line the person pastes, the note, a hint of where the code is), so a part that costs is found and cut. A value nobody measured is written N/A, never 0. The limits are published with the result. Until a round shows a saving, modfence does not claim one: so far it cost 18% to 54% more on well-specified tasks (5% on rich once its misassigned task is left out) and 21% less on vague ones.
*Done when:* the latest A/B is in the docs with its runs, and every number in the docs links to the run that produced it.

**7. Complete first, then the least that works.**
Every step of the loop works end to end in a plain form before any step is made better: a crude piece that exists beats a polished piece that is missing. Each piece is the least that works: check whether the codebase, the standard library or Claude Code already does it, build it for the terminal first and draw it on the map second, and keep anything the agent reads from modfence (fence note, brief) as short as measurement allows.
*Done when:* every step in the loop table has a command that runs, and each change is the smallest diff that passes its check and adds no dependency.

## Using the rules

- A commit that changes behaviour names the rule it serves ("rule 5").
- A design names what it gains and what it costs on each rule it touches.
- When rules conflict, this order wins: **4** (working code stays safe), then **6** (the core goal, measured), then **5** (you know what changed), then the rest in number order.
