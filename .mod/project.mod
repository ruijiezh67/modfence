{
 "mod": 1,
 "kind": "project",
 "modules": [
  {
   "name": "map",
   "purpose": "Builds the module map from the code: imports, git history, copies and runtime links, the roles and modules, and MODULES.md itself.",
   "paths": [
    "modfence/analyze.py",
    "modfence/roles.py",
    "modfence/modules.py",
    "modfence/purpose.py"
   ]
  },
  {
   "name": "fence",
   "purpose": "Keeps an agent inside one module and asks the person only what it must not guess: the edit hook, the task-picked fence, the .mod intents, the runs and the done check.",
   "paths": [
    "modfence/scope_guard.py",
    "modfence/jit.py",
    "modfence/runner.py",
    "modfence/done_check.py",
    "modfence/show.py",
    "modfence/mod.py"
   ]
  },
  {
   "name": "review",
   "purpose": "Says what a round changed and what it may break: the receipt, the quiz, and the briefs agents read.",
   "paths": [
    "modfence/receipt.py",
    "modfence/quiz.py",
    "modfence/brief.py",
    "modfence/handoff.py"
   ]
  },
  {
   "name": "interface",
   "purpose": "The map in the browser and the commands in the terminal: the local server, the page, the CLI, project docs and skills.",
   "paths": [
    "modfence/server.py",
    "modfence/web/",
    "modfence/__main__.py",
    "modfence/__init__.py",
    "modfence/docs.py",
    "modfence/skills.py"
   ]
  },
  {
   "name": "plugin",
   "purpose": "The Claude Code plugin: its hooks, slash commands, skill and entry point.",
   "paths": [
    "plugin/",
    "hooks/",
    "commands/",
    "skills/",
    ".claude-plugin/"
   ]
  },
  {
   "name": "benchmarks",
   "purpose": "Scripts that measure modfence against plain agent use: tokens, correctness, roles and modules.",
   "paths": [
    "bench/"
   ]
  },
  {
   "name": "examples",
   "purpose": "Small standalone projects to try the map on.",
   "paths": [
    "examples/"
   ]
  }
 ],
 "settings": []
}