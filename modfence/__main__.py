"""modfence [PROJECT ...] [--port 8765] [--no-browser] [--test-cmd CMD]
modfence receipt [PROJECT] [--since REV] [--json]   what a change touched and may break (exit 1 on a break)

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


if __name__ == "__main__":
    sys.exit(main())
