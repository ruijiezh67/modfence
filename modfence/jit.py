"""Just-in-time fence (golden rules 4 and 6). You give Claude Code a task as usual; a UserPromptSubmit hook reads it at
that moment, finds the module of MODULES.md it most likely lives in, fences the agent to it and tells the agent where
to start. No model: the task's words against each module's function names and code. You see the guess, its evidence
and the other candidates (in Claude Code and on the map), and switch with one command or click. A fence you set
yourself is never replaced; a short follow-up ("continue", "approved") keeps the fence it has."""
import json, os, re, sys

from . import analyze, mod, modules, scope_guard
from .runner import _words, is_test

DEF = re.compile(r"^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+(\w+)", re.M)
MIN_SCORE = 8      # ponytail: below this the task names nothing in the code; calibrated on the rich and lab tasks
SECOND = 0.75      # a second module this close to the first is fenced too, so a task that spans two is not blocked
WHERE = 3          # likely places shown to the agent; more is a search it does better itself


def candidates(root, task, mods=None, k=3):
    """[{module, score, where: [(path, line, name)]}], best first. A function scores 3 per task word in its name, 1 per
    word in its body, plus the words in its file's name; a module scores the sum of its best WHERE functions."""
    q = _words(task or "")
    mods = mods if mods is not None else modules.load(root)
    if not q or not mods:
        return []
    found = {}
    for path in analyze.walk(root):
        m = modules.owner(mods, path)
        if not m or is_test(path):
            continue
        try:
            text = analyze.read_text(os.path.join(root, path))
        except (OSError, ValueError):
            continue
        in_file = len(q & _words(os.path.basename(path)))
        defs = [(d.start(), d.group(1)) for d in DEF.finditer(text)]
        for i, (at, name) in enumerate(defs):
            body = text[at:defs[i + 1][0] if i + 1 < len(defs) else len(text)]
            s = 3 * len(q & _words(name)) + len(q & _words(body)) + in_file
            if s >= 3:
                found.setdefault(m, []).append((s, path, text.count("\n", 0, at) + 1, name))
    out = []
    for m, fs in found.items():
        fs.sort(key=lambda f: (-f[0], f[1], f[2]))
        out.append({"module": m, "score": sum(f[0] for f in fs[:WHERE]), "where": [list(f[1:]) for f in fs[:WHERE]]})
    return sorted(out, key=lambda c: (-c["score"], c["module"]))[:k]


def choose(cands):
    """The modules to fence: the best, and the second when it scores nearly as well. None when the task is too vague."""
    if not cands or cands[0]["score"] < MIN_SCORE:
        return None
    return [c["module"] for c in cands[:2] if c["score"] >= SECOND * cands[0]["score"]]


def project_root(cwd):
    """The nearest folder at or above cwd with a .mod/project.mod (or a MODULES.md from before)."""
    d = os.path.abspath(cwd or os.getcwd())
    while True:
        if mod.has_project(d):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def apply(root, task):
    """Fence for this task, as the hook does. Returns (picked modules or None, candidates, current fence file)."""
    f = scope_guard._read_json(os.path.join(root, scope_guard.FENCE_FILE))
    if f is not None and f.get("by") != "jit":  # the person set this fence: theirs to change
        return None, [], f
    cands = candidates(root, task)
    pick = choose(cands)
    if pick:
        try:  # a new task: the requests of the last one are no longer pending
            os.remove(os.path.join(root, scope_guard.ASKS_FILE))
        except OSError:
            pass
        scope_guard.arm(root, ["@module:" + m for m in pick], False, " + ".join(pick), hook=False,
                        extra={"by": "jit", "task": task[:300], "candidates": cands})
    return pick, cands, f


def message(pick, cands):
    """(for the agent, for the person). Short: the agent reads it on every turn of the task."""
    names = lambda c: ", ".join(dict.fromkeys(w[2] for w in c["where"]))
    agent = (f"modfence: for this task you may edit only module {' and '.join(pick)} (and tests); an edit "
             "elsewhere is blocked until the user approves it, so try it and say why. Likely start: "
             + "; ".join(f"{p}:{n} {name}" for p, n, name in cands[0]["where"]))
    others = [c for c in cands if c["module"] not in pick]
    person = (f"modfence fenced this task to {' + '.join(pick)} ({names(cands[0])})"
              + ("; other candidates: " + ", ".join(f"{c['module']} ({names(c)})" for c in others) if others else "")
              + ". Switch: /modfence:fence <module>, or on the map.")
    return agent, person


def fence_for(task, root=None, fence=True):
    """For an agent you run yourself (the Claude API, the Agent SDK, any tool loop): the fence for this task, as the
    plugin's hook sets it. {"modules": [...] or None, "context": text to give the model or None, "message": line for
    the person or None, "candidates": [...]}. fence=False only looks. root: the project or a folder in it."""
    root = project_root(root)
    if not root:
        return {"modules": None, "context": None, "message": None, "candidates": []}
    if fence:
        pick, cands, _ = apply(root, task or "")
    else:
        cands = candidates(root, task)
        pick = choose(cands)
    agent, person = message(pick, cands) if pick else (None, None)
    return {"modules": pick, "context": agent, "message": person, "candidates": cands}


def check_edit(path, root=None):
    """For a tool loop you run yourself: None if the fence lets this file be written (or no fence is set), else the
    reason to send the model instead of writing. A denied file is recorded as a request, shown on the map."""
    root = project_root(root) or os.path.abspath(root or os.getcwd())
    fence = scope_guard.load_fence(root)
    if fence is None:
        return None
    asked = []
    reason = scope_guard.decide({"tool_name": "Write", "tool_input": {"file_path": path}}, *fence, asked=asked)
    return reason + scope_guard.log_ask(fence[0], asked[0]) if asked else reason


def hook(raw):
    """UserPromptSubmit: fence the task's module and tell both sides. Silent without MODULES.md, on a fence the person
    set, and on a follow-up too vague to point anywhere (the fence it has stays)."""
    try:
        ev = json.loads(raw or "{}")
    except ValueError:
        return 0
    root = project_root(ev.get("cwd"))
    if not root:
        return 0
    pick, cands, _ = apply(root, ev.get("prompt") or "")
    if not pick:
        return 0
    agent, person = message(pick, cands)
    print(json.dumps({"systemMessage": person, "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": agent}}))
    return 0


def main(argv):
    """modfence jit "<task>" [--project P]: what the hook would fence for this task, without fencing. --hook: the hook."""
    if argv[:1] == ["--hook"]:
        return hook(sys.stdin.read())
    root = os.path.abspath(argv[argv.index("--project") + 1]) if "--project" in argv else project_root(os.getcwd())
    task = " ".join(a for i, a in enumerate(argv) if a != "--project" and (i == 0 or argv[i - 1] != "--project"))
    if not root:
        print(f"modfence: no {modules.FILE} here or above; save one from the map first.", file=sys.stderr)
        return 2
    cands = candidates(root, task)
    pick = choose(cands)
    for c in cands:
        print(f"{c['module']:16} {c['score']:>4}  " + "; ".join(f"{p}:{n} {name}" for p, n, name in c["where"]))
    print("would fence: " + (" + ".join(pick) if pick else "nothing (too vague: the fence it has stays)"))
    return 0
