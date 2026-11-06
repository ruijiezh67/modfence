"""python -m modfence [PROJECT ...] [--port 8765] [--no-browser]

With no project given, opens the example projects in examples/.
"""
import argparse, glob, os, sys

from .server import serve

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modfence", description="See your project as modules, and prompt Claude about one module at a time.")
    ap.add_argument("projects", nargs="*", help="project folders (default: the bundled examples)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--claude", help="path to the Claude Code CLI (default: CLAUDE_BIN, the VS Code bundle, or PATH)")
    a = ap.parse_args(argv)
    projects = a.projects or sorted(p for p in glob.glob(os.path.join(HERE, "examples", "*")) if os.path.isdir(p))
    if not projects:
        print("modfence: no project given and no examples found", file=sys.stderr)
        return 2
    serve(projects, port=a.port, claude_bin=a.claude, open_browser=not a.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
