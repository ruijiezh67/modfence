"""modfence [PROJECT ...] [--port 8765] [--no-browser] [--test-cmd CMD]
modfence receipt [PROJECT] [--since REV] [--json]   what a change touched and may break (exit 1 on a break)
modfence receipt --fleet [PROJECT] [--base main]   one receipt per worktree, for many agents at once
modfence quiz [PROJECT] [--since REV]              five questions on the round: do you still know what it did?
modfence fence MODULE | --off                       fence every agent in this project to one module of MODULES.md

With no project given, opens the current directory if it holds Python files, else the bundled examples.
"""
import argparse, glob, os, sys

from .analyze import walk
from .server import join_running, serve

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["receipt"]:  # what a change touched and broke, in the terminal (golden rule 5)
        from . import receipt
        return receipt.main(argv[1:])
    if argv[:1] == ["quiz"]:  # do you still know what the agent did? (golden rule 3)
        from . import quiz
        return quiz.main(argv[1:])
    if argv[:1] == ["fence"]:  # a fence from the terminal, for any agent in this project (golden rule 4)
        return fence(argv[1:])
    if argv[:1] == ["guard"]:  # the PreToolUse hook itself, as the plugin runs it
        from . import scope_guard
        sys.argv = sys.argv[:1]  # the hook reads the project from its working directory
        return scope_guard.main()
    ap = argparse.ArgumentParser(prog="modfence", description="See your project as modules, and prompt Claude about one module at a time.")
    ap.add_argument("projects", nargs="*", help="project folders (default: the current directory, else the bundled examples)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--claude", help="path to the Claude Code CLI (default: CLAUDE_BIN, the VS Code bundle, or PATH)")
    ap.add_argument("--test-cmd", help="shell command for the project's tests (default: pytest if configured, else unittest)")
    a = ap.parse_args(argv)
    if a.test_cmd:
        os.environ["MODFENCE_TEST_CMD"] = a.test_cmd  # read by the Tests button and by the done check's hook
    projects = a.projects or ([os.getcwd()] if walk(os.getcwd()) else
                              sorted(p for p in glob.glob(os.path.join(HERE, "examples", "*")) if os.path.isdir(p)))
    if not projects:
        print("modfence: no Python files here; pass a project folder", file=sys.stderr)
        return 2
    if join_running(a.port, projects, open_browser=not a.no_browser):  # one server, one port, many projects
        return 0
    serve(projects, port=a.port, claude_bin=a.claude, open_browser=not a.no_browser)
    return 0


def fence(argv):
    """modfence fence <module> [--sealed] | --off: fence every agent in this project to one module of MODULES.md."""
    from . import modules, scope_guard
    ap = argparse.ArgumentParser(prog="modfence fence", description="Fence agents in this project to one module of MODULES.md.")
    ap.add_argument("module", nargs="?")
    ap.add_argument("--off", action="store_true", help="lift the fence")
    ap.add_argument("--sealed", action="store_true", help="also hide other modules' code from the agent")
    ap.add_argument("--project", default=os.getcwd())
    a = ap.parse_args(argv)
    root = os.path.abspath(a.project)
    if a.off:
        scope_guard.disarm(root)
        print("modfence: fence off.")
        return 0
    mods = modules.load(root)
    if not mods:
        print(f"modfence: no {modules.FILE} in {root}. Open the map and save its modules first.", file=sys.stderr)
        return 2
    names = [m["name"] for m in mods]
    m = next((m for m in mods if m["name"].lower() == (a.module or "").lower()), None)
    if m is None:
        print("modfence: name a module: " + ", ".join(names), file=sys.stderr)
        return 2
    scope_guard.arm(root, ["@module:" + m["name"]], a.sealed, m["name"])
    print(f"modfence: fence on {m['name']} ({', '.join(m['paths'][:6])}{' ...' if len(m['paths']) > 6 else ''}); tests stay open. "
          f"Edits outside it are blocked for every agent in this project. `modfence fence --off` lifts it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
