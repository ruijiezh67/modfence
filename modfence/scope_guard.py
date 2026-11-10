"""Claude Code PreToolUse hook: edits only inside the fence, and in a sealed run, reads only inside it too.

modfence starts each run with:
- MODFENCE_ROOT, the project root;
- MODFENCE_SCOPE, what may be edited: directories or files relative to the root, separated by os.pathsep; "." means
  the files directly in the root;
- for a sealed run (golden rule 4), MODFENCE_SEAL=1 and MODFENCE_FENCE, what may be read the same way.

Edits outside the scope are always denied. In a sealed run the agent also cannot read other modules' code. A Read of a
.py file outside the fence is denied, and the denial carries that file's interface (its stubs), so the agent still
learns what it needs at a fraction of the tokens. Grep must stay inside the fence. Bash may only run tests, git
status/diff/log, ls, and the escape hatch `show.py` (logged in the run).
Tests and non-Python files stay readable. A hook error denies (fail closed), because the fence is the promise.

Without those variables the fence comes from <root>/.modfence/fence.json, written by arm() while the UI has a fence
set, with this hook added to <root>/.claude/settings.local.json. So an agent the user starts by hand (Claude Code,
Cursor, Copilot, Codex) is fenced too. Payloads in Claude Code, Cursor, Copilot (toolName, toolArgs) and Codex
(apply_patch) shapes are read; an unknown tool whose name says it changes files is denied. No fence: allow everything.
"""
import json, os, re, sys
from datetime import datetime

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
ALIAS = {"edit": "Edit", "write": "Write", "create": "Write", "delete": "Write", "multiedit": "MultiEdit",
         "notebookedit": "NotebookEdit", "read": "Read", "view": "Read", "grep": "Grep", "bash": "Bash", "shell": "Bash"}
MUTATING = re.compile(r"write|edit|delete|patch|move|create|rename", re.I)
NOT_FILES = ("TodoWrite", "TaskCreate", "CronCreate")  # ponytail: Claude Code tools named like edits that touch no file
PATCH_PATH = re.compile(r"^\*\*\* (?:Update File|Add File|Delete File|Move to): (.+)$", re.M)
PATH_KEYS = ("file_path", "notebook_path", "path", "filePath", "target_file")
FENCE_FILE = os.path.join(".modfence", "fence.json")
LOCAL_SETTINGS = os.path.join(".claude", "settings.local.json")
# Golden rule 4 (no turns, no time): the hook starts a Python process, about 0.35 s on Windows, so it runs only on the
# tools that can edit; a sealed fence also checks reads, searches and commands.
EDIT_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|mcp__.*"
ASKS_FILE = os.path.join(".modfence", "asks.jsonl")  # edits the fence file's fence denied: the UI shows them for approval
SEAL_TOOLS = ("Read", "Grep", "Bash")
BASH_OK = re.compile(r"^\s*(\S*python[0-9.]*(\.exe)?\"?\s+-m\s+(pytest|unittest)\b|pytest\b|git\s+(status|diff|log)\b|ls\b|"
                     r"\S*python[0-9.]*(\.exe)?\"?\s+\"?\S*show\.py\"?\s)")
BASH_META = re.compile(r"[;&|`<>]|\$\(")  # chaining or redirection could read anything after an allowed prefix


def _rel(path, root):
    full = os.path.normcase(os.path.realpath(os.path.join(root, path)))
    root_n = os.path.normcase(os.path.realpath(root))
    if os.path.commonpath([full, root_n]) != root_n:
        return None
    return os.path.relpath(full, root_n).replace(os.sep, "/")


def _module_owner(root, rel):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from modfence import modules
    return modules.owner(modules.load(root), rel)


def allowed(path, root, scope):
    """Is path (absolute or relative to root) inside one of the scope entries? An entry "@module:NAME" is a module of
    MODULES.md: the files whose longest matching line is that module's, new files included, and every test file."""
    rel = _rel(path, root)
    if rel is None:
        return False
    for s in scope:
        if s.startswith("@module:"):
            if _is_test(rel) or _module_owner(root, rel) == s[len("@module:"):]:
                return True
            continue
        s = s.strip("/")
        if s in ("", "."):
            if "/" not in rel:
                return True
        elif rel == s or rel.startswith(s + "/"):
            return True
    return False


def _is_test(rel):
    parts = rel.split("/")
    return any(p in ("tests", "test") for p in parts[:-1]) or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def _stubs(root, rel):
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from modfence import brief
        return "\n".join(brief.file_stub(root, rel, 40)) or "(nothing public)"
    except Exception as e:  # the denial still stands; only the courtesy failed
        return f"(interface unavailable: {type(e).__name__})"


def normalise(event):
    """(tool, input) in Claude Code's names, from a Claude Code, Cursor, Copilot or Codex payload."""
    tool = event.get("tool_name") or event.get("toolName") or ""
    ti = event.get("tool_input") or event.get("toolArgs") or {}
    if isinstance(ti, str):  # Copilot sends its arguments as a JSON string
        ti = json.loads(ti)
    return ALIAS.get(tool.lower(), tool), ti


def patch_paths(text):
    """Every file an apply_patch text adds, updates, deletes or moves to."""
    return [p.strip() for p in PATCH_PATH.findall(text)]


def decide(event, root, scope, fence=None, asked=None):
    """None to allow, or the reason to deny. fence: what a sealed run may read (None: not sealed). asked: a list that
    gets the project path of an edit denied for being outside the scope."""
    tool, ti = normalise(event)
    text = ti.get("command") or ti.get("input") or ""
    text = "\n".join(text) if isinstance(text, list) else str(text)
    if tool == "apply_patch" or "*** Begin Patch" in text:
        paths = patch_paths(text)
    elif tool in EDIT_TOOLS:
        paths = [next((ti[k] for k in PATH_KEYS if ti.get(k)), None)]
    elif tool not in NOT_FILES and MUTATING.search(tool):
        return f"modfence: {tool} may change files and modfence cannot check where, so it is blocked while a fence is set."
    else:
        paths = None
    if paths is not None:
        if not paths or not all(paths):
            return "modfence: no file path in this edit, so its scope cannot be checked."
        path = next((p for p in paths if not allowed(p, root, scope)), None)
        if path is None:
            return None
        if asked is not None and _rel(path, root):
            asked.append(_rel(path, root))
        return (f"modfence scope: {path} is outside the modules you may edit ({', '.join(scope) or '(nothing)'}). Do not try "
                "another way to change it. Finish what you can inside the scope, then end your turn with one line per file "
                "you need, exactly: NEED <path>: <the change and why>. The user approves or refuses each; if approved, "
                "you continue in this same conversation with the file in your scope.")
    if fence is None or tool not in SEAL_TOOLS:
        return None
    if tool == "Read":
        path = next((ti[k] for k in PATH_KEYS if ti.get(k)), "")
        rel = _rel(path, root)
        if rel is None or not rel.endswith(".py") or _is_test(rel) or allowed(path, root, fence):
            return None
        return (f"modfence seal: {rel} is another module's code, hidden in this run so you cannot depend on or break its "
                f"internals. Its interface:\n{_stubs(root, rel)}\nWork from this interface. If you truly need one "
                "definition's docstring, run the show command from your instructions.")
    if tool == "Grep":
        path = ti.get("path") or "."
        if allowed(path, root, fence) and (_rel(path, root) or "") not in ("", "."):
            return None
        return ("modfence seal: search inside the fence only: pass path= one of " + ", ".join(fence[:8])
                + ". Other modules are described in your instructions.")
    cmd = ti.get("command") or ""
    if BASH_OK.match(cmd) and not BASH_META.search(cmd):
        return None
    return ("modfence seal: in this run Bash may only run the tests, git status/diff/log, ls, or the show command from "
            "your instructions (no chaining or redirection).")


def _list(name):
    return [s for s in os.environ.get(name, "").split(os.pathsep) if s]


def load_fence(root):
    """(root, scope, fence) from the runner's variables, else from root's fence file; None when no fence is set."""
    if "MODFENCE_ROOT" in os.environ:
        sealed = os.environ.get("MODFENCE_SEAL") == "1"
        return os.environ["MODFENCE_ROOT"], _list("MODFENCE_SCOPE"), _list("MODFENCE_FENCE") if sealed else None
    f = _read_json(os.path.join(root, FENCE_FILE))
    return None if f is None else (root, f["files"], f["files"] if f.get("sealed") else None)


def log_ask(root, path):
    """Record a denied file as a request the map shows the person; returns the sentence to add for the agent."""
    with open(os.path.join(root, ASKS_FILE), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"path": path, "at": datetime.now().astimezone().isoformat(timespec="seconds")}) + "\n")
    return " modfence shows the user this request; they will tell you when it is approved."


def pending_asks(root, scope, answered=()):
    """The files an agent was denied since the fence was armed, oldest first, minus those answered or now inside."""
    try:
        with open(os.path.join(root, ASKS_FILE), encoding="utf-8") as f:
            paths = [json.loads(line)["path"] for line in f if line.strip()]
    except (OSError, ValueError, KeyError):
        return []
    return [p for p in dict.fromkeys(paths) if p not in answered and not allowed(p, root, scope)]


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {"tool_name": "Edit"}  # unreadable input: treat as an edit, so it is denied below
    try:
        fence = load_fence(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
        if fence is None:
            return 0
        asked = None if "MODFENCE_ROOT" in os.environ else []  # an agent the user started: modfence's UI asks the user
        reason = decide(event, *fence, asked=asked)
        if asked:
            reason += log_ask(fence[0], asked[0])
    except Exception as e:  # fail closed
        reason = f"modfence scope guard error ({type(e).__name__}: {e}); blocked."
    if not reason:
        return 0
    # Claude Code and Cursor read hookSpecificOutput, Copilot and others the top-level keys; exit 2 with stderr blocks in all
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason},
                      "permissionDecision": "deny", "permissionDecisionReason": reason, "decision": "block", "reason": reason}))
    sys.stderr.write(reason + "\n")
    return 2


# ----- arm / disarm: the fence for agents the user starts by hand -----
def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2)


def _ours(entry):
    return any("scope_guard" in (h.get("command") or "") for h in entry.get("hooks") or [])


def hook_command(root):
    q = lambda p: '"' + os.path.abspath(p).replace("\\", "/") + '"'  # quoted, forward slashes: works in a POSIX shell on Windows too
    return f"{q(sys.executable)} {q(__file__)} {q(root)}"


def arm(root, files, sealed, label="", hook=True, extra=None):
    """Write the fence file and add this hook to root's .claude/settings.local.json, keeping everything else there.
    hook=False: the fence file only, for the plugin, whose own hook reads it. extra: more fields for the file (the
    just-in-time fence keeps the task and the candidates there, for the map)."""
    root = os.path.abspath(root)
    fence_path, settings_path = os.path.join(root, FENCE_FILE), os.path.join(root, LOCAL_SETTINGS)
    settings = _read_json(settings_path)
    made = (_read_json(fence_path) or {}).get("made_settings", settings is None)  # kept across re-arms
    _write_json(fence_path, {"files": sorted({f.split("::")[0] for f in files}), "sealed": bool(sealed), "label": label,
                             "since": datetime.now().astimezone().isoformat(timespec="seconds"), "made_settings": made, **(extra or {})})
    gi = os.path.join(root, ".modfence", ".gitignore")
    if not os.path.exists(gi):  # as runner.state_dir does: modfence's state stays out of git
        with open(gi, "w", newline="\n") as f:
            f.write("*\n")
    if not hook:
        return
    settings = settings or {}
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    entry = {"matcher": "*" if sealed else EDIT_MATCHER, "hooks": [{"type": "command", "command": hook_command(root), "timeout": 10}]}
    if entry not in pre:  # one entry of ours, matching what this fence must see
        pre[:] = [e for e in pre if not _ours(e)] + [entry]
        _write_json(settings_path, settings)


def disarm(root):
    """Remove the fence file and only modfence's hook; delete settings.local.json if modfence made it and it is now empty."""
    root = os.path.abspath(root)
    fence_path, settings_path = os.path.join(root, FENCE_FILE), os.path.join(root, LOCAL_SETTINGS)
    made = (_read_json(fence_path) or {}).get("made_settings", False)
    for p in (fence_path, os.path.join(root, ASKS_FILE)):
        if os.path.exists(p):
            os.remove(p)
    settings = _read_json(settings_path)
    pre = ((settings or {}).get("hooks") or {}).get("PreToolUse") or []
    if not any(_ours(e) for e in pre):
        return
    settings["hooks"]["PreToolUse"] = [e for e in pre if not _ours(e)]
    for key, d in (("PreToolUse", settings["hooks"]), ("hooks", settings)):
        if not d[key]:
            del d[key]
    if made and not settings:
        os.remove(settings_path)
        try:
            os.rmdir(os.path.dirname(settings_path))  # only if empty
        except OSError:
            pass
    else:
        _write_json(settings_path, settings)


if __name__ == "__main__":
    sys.exit(main())
