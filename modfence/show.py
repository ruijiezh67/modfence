"""The seal's escape hatch, runnable by path from any project: `python <this file> path/to/file.py[::name]`.

Prints a file's interface, or one name's stub with its full docstring, never its body (golden rule 4). Every use shows
in the run log; frequent use means the brief is missing something (golden rule 7).
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence import brief  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python show.py path/to/file.py[::name]")
        sys.exit(2)
    print(brief.show(os.environ.get("MODFENCE_ROOT", os.getcwd()), sys.argv[1]))
