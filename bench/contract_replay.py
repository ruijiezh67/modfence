"""Replay a git history through modfence's contract check (golden rule 3), at zero model cost.

For each commit, the parent tree is analyzed (import graph with receipts), and every .py file the commit modified or
deleted is checked: did it break a name another module used at the parent? Each flag is then sorted by what the commit
did with the users of that name:

- users updated in the same commit: the break was real and handled together (a true positive the user would want to see);
- users not updated: either a real break left behind, or a false alarm (read these by hand).

Usage: python bench/contract_replay.py REPO [--max N] > out.md
Needs git on PATH. Reads the repository with `git archive` into a temporary folder; changes nothing in it.
"""
import io, os, subprocess, sys, tarfile, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence import analyze, brief  # noqa: E402


def git(repo, *args, binary=False):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


def tree_at(repo, rev, into):
    data = git(repo, "archive", "--format=tar", rev, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(into, filter="data")


def blob(repo, rev, path):
    try:
        return git(repo, "show", f"{rev}:{path}", binary=True)
    except subprocess.CalledProcessError:
        return None


def main():
    repo = os.path.abspath(sys.argv[1])
    n = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 200
    commits = git(repo, "rev-list", "--no-merges", f"--max-count={n}", "HEAD").split()
    rows, checked, flagged_commits = [], 0, 0
    for c in commits:
        parents = git(repo, "rev-list", "--parents", "-n", "1", c).split()[1:]
        if len(parents) != 1:
            continue
        p = parents[0]
        changes = [l.split("\t") for l in git(repo, "diff", "--name-status", p, c).splitlines()]
        touched = {x[-1] for x in changes}
        py = [x[1] for x in changes if x[0][0] in "MD" and x[1].endswith(".py")]
        if not py:
            continue
        tmp = tempfile.mkdtemp(prefix="mf-replay-")
        try:
            tree_at(repo, p, tmp)
            g = analyze.analyze(tmp)
            found = brief.contract_breaks(g, {f: (blob(repo, p, f), blob(repo, c, f)) for f in py})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        checked += 1
        flagged_commits += bool(found)
        for b in found:
            users = sorted({u.rsplit(":", 1)[0] for u in b["users"]})
            handled = all(u in touched for u in users)
            rows.append((c[:8], b["file"], b["name"], b["change"], len(users), "updated" if handled else "NOT updated"))
    print(f"# Contract replay: {os.path.basename(repo)}\n")
    print(f"Commits with modified or deleted .py files checked: {checked}; commits with at least one flag: {flagged_commits}.")
    upd = sum(r[5] == "updated" for r in rows)
    print(f"Flags: {len(rows)}; users updated in the same commit: {upd}; users not updated: {len(rows) - upd}.\n")
    print("| commit | file | name | change | user files | users in same commit |\n|---|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(str(x) for x in r) + " |")


if __name__ == "__main__":
    main()
