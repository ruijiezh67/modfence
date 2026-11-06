"""Claude Code PreToolUse hook: allow file edits only inside the modules the user picked.

modfence starts each run with MODFENCE_ROOT (project root) and MODFENCE_SCOPE (allowed directories relative to the
root, separated by os.pathsep; "." means files directly in the root, not its subdirectories). Edit, Write,
MultiEdit and NotebookEdit calls on any other path are denied, so the agent cannot change code outside the
selected modules: it is told why and asked to say which module needs the change instead.
Reads are never blocked. A hook error denies the edit (fail closed), because the scope is the promise.
"""
import json, os, sys


def allowed(path, root, scope):
    """Is path (absolute or relative to root) inside one of the scope directories?"""
    full = os.path.normcase(os.path.realpath(os.path.join(root, path)))
    root_n = os.path.normcase(os.path.realpath(root))
    if os.path.commonpath([full, root_n]) != root_n:
        return False
    rel = os.path.relpath(full, root_n).replace(os.sep, "/")
    for s in scope:
        s = s.strip("/")
        if s in ("", "."):
            if "/" not in rel:
                return True
        elif rel == s or rel.startswith(s + "/"):
            return True
    return False


def decide(event, root, scope):
    """None to allow, or the reason to deny."""
    if event.get("tool_name") not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return None
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        return "modfence: no file path in this edit, so its scope cannot be checked."
    if allowed(path, root, scope):
        return None
    shown = ", ".join(scope) or "(nothing)"
    return (f"modfence scope: {path} is outside the modules you may edit ({shown}). Do not try another way to change it. "
            "Finish what you can inside the scope, then tell the user which module needs this change and why, "
            "so they can widen the scope.")


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {"tool_name": "Edit"}  # unreadable input: treat as an edit, so it is denied below
    if event.get("tool_name") not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return 0
    try:
        root = os.environ["MODFENCE_ROOT"]
        scope = [s for s in os.environ.get("MODFENCE_SCOPE", "").split(os.pathsep) if s]
        reason = decide(event, root, scope)
    except Exception as e:  # fail closed
        reason = f"modfence scope guard error ({type(e).__name__}: {e}); edit blocked."
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
