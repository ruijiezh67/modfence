---
description: Work module by module in a repository that has a MODULES.md (modfence). Use when MODULES.md exists at the project root, when a modfence fence blocks an edit, or before finishing a change in such a repository.
---
# Working with MODULES.md

`MODULES.md` at the project root is the team's agreement on who holds which module. Several people may be working at once, each with their own agent, each in their own module.

1. Read `MODULES.md` first. Name the one module the task belongs to before you edit.
2. Stay inside that module. Tests belong to no module: you may add and run them.
3. If a modfence fence blocks an edit, do not look for another way to make it. Finish the part inside the module, then tell the user which file in which module needs what change, and why.
4. Before you finish, run `/modfence:receipt` (the Stop hook also does). Fix a broken contract or a new cross-module dependency, or say why it is intended.
