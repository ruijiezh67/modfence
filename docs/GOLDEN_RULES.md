# Golden rules

modfence exists for one thing: **module vibe coding**. You understand your project as modules, then direct the AI module by module. Every design choice and every revision is checked against the seven rules below. If a change serves none of them, it does not ship. If it breaks one, it needs a written reason.

1. **Save tokens.** Build the project's graph deterministically, with no model call wherever code can do it. Build two outputs from it: a picture for the user, and a compact document for the AI only. That document is written for the model, not for people. Treat it like a latent: it can be unreadable to a person, and its format is whatever measures best on tokens multiplied by task success. It must replace the AI's own grep-and-read exploration.

2. **Code through a picture.** The graph is how a programmer sees what they are doing: which module does what, which ones talk to each other, and what a change touched. Each view must help someone understand or act. A view that only decorates is removed.

3. **Module-wise versions that git and AI undo do not give.** Git and the AI's own undo already restore code, so modfence does not copy them. Its version feature must answer a module-level question those tools cannot, such as what this module promised the rest of the system before the run and whether it still does.

4. **The fence protects what already works.** During a revision, the AI works inside the fenced module. It sees other modules only through the compact document: their names, purposes and interfaces, not their code. It must not break functions that other modules rely on. The harness enforces this; the prompt alone does not.

5. **No function-level graphs.** Nobody wants to read them. Inside a module, a secondary graph of the module's parts is allowed only when it makes the module easier to interpret.

6. **How the graph is built is the core.** Prefer deterministic analysis, and reuse proven open-source methods where they fit. A model may name or summarize, never decide structure on its own. Every model call must show its token cost and what it saves. A call that does not save more than it costs is removed.

7. **Modules isolate, and every round says which modules it changed.** Modularity is isolation: a module is a unit the AI can change in one round without touching the others. After every round, the user sees at a glance which modules it changed and which modules use the changed code, on the graph and in History. Nothing changes unnoticed.

## How to use these rules

- Every pull request and commit that changes behaviour names the rule it serves.
- A measurement backs every claim about tokens or safety. A number that was not measured is written N/A, never 0.
- Every design is a trade-off among the seven rules. Name what it gains and what it costs on each rule it touches.
- When two rules conflict, the earlier one wins, except rules 4 and 7: never trade the safety of working code, or knowing what a round changed, for tokens.
