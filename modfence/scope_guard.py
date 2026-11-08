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
"""
import json, os, re, sys

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
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


def allowed(path, root, scope):
    """Is path (absolute or relative to root) inside one of the scope entries?"""
    rel = _rel(path, root)
    if rel is None:
        return False
    for s in scope:
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


def decide(event, root, scope, fence=None):
    """None to allow, or the reason to deny. fence: what a sealed run may read (None: not sealed)."""
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path")
        if not path:
            return "modfence: no file path in this edit, so its scope cannot be checked."
        if allowed(path, root, scope):
            return None
        return (f"modfence scope: {path} is outside the modules you may edit ({', '.join(scope) or '(nothing)'}). Do not try "
                "another way to change it. Finish what you can inside the scope, then tell the user which module needs "
                "this change and why, so they can widen the scope.")
    if fence is None or tool not in SEAL_TOOLS:
        return None
    if tool == "Read":
        path = ti.get("file_path") or ""
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


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {"tool_name": "Edit"}  # unreadable input: treat as an edit, so it is denied below
    sealed = os.environ.get("MODFENCE_SEAL") == "1"
    if event.get("tool_name") not in EDIT_TOOLS + (SEAL_TOOLS if sealed else ()):
        return 0
    try:
        root = os.environ["MODFENCE_ROOT"]
        reason = decide(event, root, _list("MODFENCE_SCOPE"), _list("MODFENCE_FENCE") if sealed else None)
    except Exception as e:  # fail closed
        reason = f"modfence scope guard error ({type(e).__name__}: {e}); blocked."
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
