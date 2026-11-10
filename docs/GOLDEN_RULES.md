# Golden rules

modfence exists for **module vibe coding**: the project is a few modules, an agent works inside one module at a time, and every round leaves a receipt of what it touched.

The fence is the point. Because each person, and each person's agent, can change only the module they hold, several people can work on one codebase at once without breaking each other's work, whichever agent each of them uses. `MODULES.md` is the agreement on who holds what. A feature that weakens this does not ship. **For now modfence supports Claude Code only**; other agents (Codex, Cursor, Copilot) come once people use it, and nothing is built that would rule them out.

It serves two kinds of user, and every feature must work for at least one of them:

- **Engineers who live in the terminal** and run agents, often several at once or in loops. They get the fence and the receipt as a Claude Code plugin and a command line, with no page to open.
- **People who need to see the project first**: newcomers, reviewers, anyone taking over code they did not write. They get the map.

## What the field taught us

Four lessons from the people who run agents every day (posts on X, 2025-2026) and from our own measurements. The rules below follow from them.

1. **Review is the limit, not the agent.** "Your review bandwidth decides how many you can actually run, not the tool" (Addy Osmani). modfence makes review cheap: a change is read as modules, not as a diff.
2. **People still read the code that matters.** Karpathy kept vibe coding to "throwaway weekend projects"; Mitchell Hashimoto's planner, coder and judge loop ends with "I read the code". modfence keeps the person's understanding; it does not replace it.
3. **Verification beats instructions.** The most-liked tip in Boris Cherny's thread is "give Claude a way to verify its work". modfence's guarantees are hooks and checks, not prompt text.
4. **A map handed to the agent costs more than it saves.** ContextMesh measured a repo map at +36% to +46% tokens with no turns saved. Our own A/B (36 runs, 4 real tasks) measured the fence at +19% to +29% cost: a well-specified task already sends the agent to the right files (2.3 files read, none outside the module), and what costs tokens is turns times context, which the fence did not reduce. The map is for people; what the agent reads from modfence stays minimal.

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
*Next:* measure that (rule 6): ask a person those two questions after a round, with and without modfence.

## B. Agents

**4. The fence is a hook, granted per module.**
While a fence is set, a hook blocks any edit outside the fenced module, so two people, or two agents in two worktrees, can work on two modules at once. A person grants and lifts a module for an agent from the map or from the terminal, and crossing into another module needs that person's approval. The fence must not cost the agent turns: hiding other modules' code ("sealed") made agents hit the hook about twice a run for no measured gain, so it is off unless a measurement shows it pays.
*Done when:* a test shows the hook denying an outside edit by Claude Code, and two fences set in two worktrees of one repository do not affect each other.

**5. Every round leaves a receipt, built for review.**
After a round, the receipt says which modules changed, which modules use them, which names other modules rely on were broken, which cross-module dependencies are new, which files are outside the fence, and which tests to run. It comes from git and static analysis, with no model. On a break it blocks the agent once, then lets it stop. It is shown on the map and in the terminal, and it reads in seconds, because review is the limit (lesson 1).
*Done when:* `modfence receipt` reports all of these and exits non-zero on a break, and the map highlights the changed boxes.
*Next:* review many agents at once: one receipt per branch or worktree (`--since main`), then one view that lays the receipts of 10 to 100 parallel agents side by side, by module.

## C. Decisions

**6. Measured, or not claimed.**
A claim about tokens, cost, correctness, safety or understanding needs an A/B on a real project, at least 3 runs per arm, with the same task for every arm. Cost is counted per outcome, as dollars per change that passed its tests and was kept, not per run. A value nobody measured is written N/A, never 0. The limits are published with the result. modfence does not claim to save tokens: the measurement so far says it does not.
*Done when:* every number in the docs links to the run that produced it.

**7. Do the least that works.**
Before building anything, check whether the codebase, the standard library or Claude Code already does it. A feature works in the terminal first and is drawn on the map second. Anything the agent reads from modfence (fence note, brief) is as short as measurement allows.
*Done when:* the change is the smallest diff that passes its check, and it adds no dependency.

## Using the rules

- A commit that changes behaviour names the rule it serves ("rule 5").
- A design names what it gains and what it costs on each rule it touches.
- When rules conflict, this order wins: **4** (working code stays safe), then **5** (you know what changed), then **6** (evidence), then the rest in number order.
