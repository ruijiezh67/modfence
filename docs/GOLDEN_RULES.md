# Golden rules

modfence exists for **module vibe coding**: the project is a few modules, an agent works inside one module at a time, and every round leaves a receipt of what it touched.

The fence is the point. Because each person, and each person's agent, can change only the module they hold, several people can work on one codebase at once without breaking each other's work, **whichever agent each of them uses** (Claude Code, Codex, Cursor, Copilot). `MODULES.md` is the agreement on who holds what. A feature that weakens this, or that works for only one agent, does not ship.

It serves two kinds of user, and every feature must work for at least one of them:

- **Engineers who live in the terminal** and run agents, often several at once or in loops. They get the fence and the receipt from a command line and hooks that any agent can use, packaged as a plugin where an agent supports plugins, with no page to open.
- **People who need to see the project first**: newcomers, reviewers, anyone taking over code they did not write. They get the map.

The seven rules come in three groups. Each rule has a **Done when** line: a check that a reviewer, a test or a script can run. A change that serves no rule does not ship. A change that breaks one needs a written reason.

## A. Modules

**1. Modules are written down and shared.**
The first level is at most 7 modules, kept in `MODULES.md` at the repository root (a name, one line of purpose, folders and globs). People, every agent (it is plain Markdown that `CLAUDE.md` and `AGENTS.md` point to), hooks and CI read the same file, so a team shares one picture of who holds what. modfence writes it only when the user saves the map. Test files belong to no module: everyone may run and extend them.
*Done when:* every feature that needs module membership reads `MODULES.md` when it exists, and a file no module claims is shown as unassigned, not guessed.

**2. Structure is computed, not guessed.**
Imports, git history, copies and runtime links decide the structure. A model may name and summarize, never decide on its own. Prefer proven open-source methods to new ones.
*Done when:* the structure can be rebuilt with no model call, and every model call shows its token cost.

**3. People see modules, not functions.**
The map shows at most 7 boxes, links that say what they mean, and what the last round changed. Inside a module, one level of parts is allowed if it makes the module easier to read. There are no function-level graphs and no decoration.
*Done when:* every element on screen answers "what does this do", "what uses what", or "what changed".

## B. Agents

**4. The fence is a hook, not a prompt.**
While a fence is set, a hook blocks any edit outside the fenced module, so two people, or two agents in two worktrees, can work on two modules at once. Crossing into another module needs the approval of the person who set the fence, given in the map or in the terminal. Whether other modules' code is also hidden from the agent ("sealed") is a choice backed by measurement, not a default taken on faith.
*Done when:* a test shows the hook denying an outside edit in the payload of each agent it claims to cover (Claude Code, Codex, Cursor, Copilot), and two fences set in two worktrees of one repository do not affect each other.

**5. Every round leaves a receipt.**
After a round, the receipt says which modules changed, which modules use them, which names other modules rely on were broken, which cross-module dependencies are new, which files are outside the fence, and which tests to run. It comes from git and static analysis, with no model. On a break it blocks the agent once, then lets it stop. It is shown on the map and in the terminal.
*Done when:* `modfence receipt` reports all of these and exits non-zero on a break, and the map highlights the changed boxes.

## C. Decisions

**6. Measured, or not claimed.**
A claim about tokens, cost, correctness or safety needs an A/B on a real project, at least 3 runs per arm, with the same task for every arm. A value nobody measured is written N/A, never 0. The limits are published with the result. modfence does not claim to save tokens until a measurement shows it.
*Done when:* every number in the docs links to the run that produced it.

**7. Do the least that works.**
Before building anything, check whether the codebase, the standard library or Claude Code already does it. A feature works in the terminal first and is drawn on the map second. Anything the agent reads from modfence (fence note, brief) is as short as measurement allows.
*Done when:* the change is the smallest diff that passes its check, and it adds no dependency.

## Using the rules

- A commit that changes behaviour names the rule it serves ("rule 5").
- A design names what it gains and what it costs on each rule it touches.
- When rules conflict, this order wins: **4** (working code stays safe), then **5** (you know what changed), then **6** (evidence), then the rest in number order.
