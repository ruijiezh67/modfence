"""modfence receipt: what a change touched and what it may break, from git, with no UI and no model (golden rule 5).

    modfence receipt [PROJECT] [--since REV] [--json]
    modfence receipt --fleet [PROJECT] [--base main]   one receipt per git worktree (one per agent), against the base

Compares the working tree with REV (default HEAD), untracked files included, whichever agent or person made the change:
- the modules it changed, with the lines added and removed;
- the modules that use them, which the change may break;
- contract breaks: names another module uses whose signature changed or that went away, with the lines that use them;
- new cross-module dependencies: a part of the map now importing a part it did not import before, anywhere;
- the files changed outside the fence, when one is set (.modfence/fence.json), and the edits the fence blocked;
- the functions added, changed and removed;
- whether MODULES.md is still true: lines that match no file, and code files no module claims;
- the test files that cover the changed modules and their users.
Exit status 1 when a contract broke, a file outside the fence changed or a new cross-module dependency appeared, so
a hook or CI can block on it; 0 otherwise; 2 when PROJECT is not a git work tree.

--hook: a Claude Code Stop hook. Only in a project with MODULES.md; on a problem it blocks the agent's stop once with
the receipt as the reason, and lets the second stop through.
"""
import argparse, ast, json, os, subprocess, sys

from . import analyze, brief, modules, roles, runner, scope_guard

SKIP = (".modfence/", ".claude/")


def _git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip())
    return r.stdout


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def changes(root, since="HEAD"):
    """[{path, status: added|modified|deleted, plus, minus}] between `since` and the working tree, untracked included."""
    status = {}
    for line in _git(root, "diff", "--name-status", "--no-renames", since, "--").decode("utf-8", "replace").splitlines():
        code, path = line.split("\t", 1)
        status[path] = {"A": "added", "D": "deleted"}.get(code[0], "modified")
    counts = {}
    for line in _git(root, "diff", "--numstat", "--no-renames", since, "--").decode("utf-8", "replace").splitlines():
        plus, minus, path = line.split("\t", 2)
        counts[path] = (None if plus == "-" else int(plus), None if minus == "-" else int(minus))  # "-": binary
    for path in _git(root, "ls-files", "--others", "--exclude-standard").decode("utf-8", "replace").splitlines():
        status[path] = "added"
        counts[path] = (len(analyze.read_text(os.path.join(root, path)).splitlines()) if path.endswith(".py") else None, 0)
    return [{"path": p, "status": s, "plus": counts.get(p, (None, None))[0], "minus": counts.get(p, (None, None))[1]}
            for p, s in sorted(status.items()) if not p.startswith(SKIP)]


def _pairs(path, data, files, part, learned=()):
    """{(part of path, part it imports): line} for one file's source."""
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError):
        return {}
    src, out = part(path), {}
    for target, line, _ in analyze.imports_of(path, tree, files, learned):
        dst = part(target)
        if src and dst and src != dst:
            out.setdefault((src, dst), f"{path}:{line}")
    return out


def new_dependencies(root, files, changed, before, part, learned=()):
    """[{"from", "to", "at"}]: part-to-part imports the changed files make now that no file made before."""
    files = set(files)
    base, now = set(), {}
    for path in files:
        if path in changed:
            continue
        try:
            base |= set(_pairs(path, analyze.read_text(os.path.join(root, path)), files, part, learned))
        except OSError:
            pass
    for path in changed:
        old = before(path)
        if old is not None:
            base |= set(_pairs(path, old, files, part, learned))
        if os.path.exists(os.path.join(root, path)):
            now.update({k: v for k, v in _pairs(path, analyze.read_text(os.path.join(root, path)), files, part, learned).items() if k not in now})
    return [{"from": a, "to": b, "at": at} for (a, b), at in sorted(now.items()) if (a, b) not in base]


def build(root, since="HEAD"):
    root = os.path.abspath(root)
    files = changes(root, since)
    graph = analyze.analyze(root)
    split = set(graph.get("split", ()))
    py = [f for f in files if f["path"].endswith(".py")]
    mods = {}
    for f in py:
        m = mods.setdefault(analyze.module_of(f["path"], split), {"files": 0, "plus": 0, "minus": 0})
        m["files"] += 1
        m["plus"] += f["plus"] or 0
        m["minus"] += f["minus"] or 0
    changed = sorted(mods)
    users = [m for m in analyze.dependents(graph, changed) if m not in mods]
    # The map's own level (golden rule 3): the areas and roles of the project, when it has them, else the modules.
    store = roles.load_store(root) or {}
    role_area = {r: a for a, v in (store.get("areas") or {}).items() for r in v.get("roles", [])}
    name = lambda d, k: ((store.get(d) or {}).get(k) or {}).get("name")
    shared = modules.load(root)  # MODULES.md first (golden rule 1), then the map's own areas
    place = lambda path: ((modules.owner(shared, path) if shared is not None else name("areas", role_area.get((store.get("files") or {}).get(path)))),
                          name("roles", (store.get("files") or {}).get(path)))
    areas = {}
    for f in py:
        area, role = place(f["path"])
        key = area or analyze.module_of(f["path"], split)
        a = areas.setdefault(key, {"id": key, "files": 0, "plus": 0, "minus": 0, "roles": []})
        a["files"] += 1; a["plus"] += f["plus"] or 0; a["minus"] += f["minus"] or 0
        if role and role not in a["roles"]:
            a["roles"].append(role)
    first = {m["id"]: m["files"][0] for m in graph["modules"] if m.get("files")}
    used_areas = sorted({place(first[m])[0] or m for m in users if m in first} - set(areas))

    def before(path):
        try:
            return _git(root, "show", f"{since}:{path}")
        except RuntimeError:
            return None
    contract = brief.contract_breaks(graph, {
        f["path"]: (None if f["status"] == "added" else before(f["path"]),
                    None if f["status"] == "deleted" else _bytes(os.path.join(root, f["path"])))
        for f in py if f["status"] != "added"})
    part = lambda path: None if modules._is_test(path) else place(path)[0] or (shared is None and analyze.module_of(path, split)) or None
    new = new_dependencies(root, graph["files"], {f["path"] for f in py if f["status"] != "deleted"}, before, part, graph.get("roots", ()))
    fence = scope_guard.load_fence(root)
    outside = [f["path"] for f in files if not scope_guard.allowed(f["path"], root, fence[1])] if fence else None
    blocked = scope_guard.pending_asks(root, [], ()) if fence else []  # every edit the fence denied this round
    funcs = []
    for f in py:
        now = None if f["status"] == "deleted" else _bytes(os.path.join(root, f["path"]))
        for u in analyze.function_changes(None if f["status"] == "added" else before(f["path"]), now) or []:
            if u["name"] != "(module level)":
                funcs.append({"file": f["path"], **u})
    stale = None
    if shared is not None:  # golden rule 1: the map must not go stale (a printed map of a city that keeps building)
        code = [p for p in graph["files"] if not modules._is_test(p)]
        every = set(graph["files"]) | set(_git(root, "ls-files").decode("utf-8", "replace").splitlines())  # not only .py: web/, hooks/
        stale = {"lines": [f"{m['name']}: {p}" for m in shared for p in m["paths"] if not any(modules.match(p, c) for c in every)],
                 "unassigned": [p for p in code if modules.owner(shared, p) is None]}
    tests = runner.select_tests(graph, [f["path"] for f in py]) if py else None
    return {"since": since, "files": files, "modules": [{"id": m, **mods[m]} for m in changed], "users": users,
            "areas": sorted(areas.values(), key=lambda a: -(a["plus"] + a["minus"])), "used_by": used_areas,
            "contract": contract, "new_dependencies": new, "outside_fence": outside, "blocked": blocked, "functions": funcs,
            "map": stale, "tests": tests["files"] if tests else [],
            "ok": not contract and not outside and not new}


def text(r):
    n = len(r["files"])
    if not n:
        return f"modfence receipt: nothing changed since {r['since']}."
    k = len(r["areas"])
    out = [f"modfence receipt: {n} file{'s' * (n != 1)} changed since {r['since']}"
           + (f", Python code in {k} part{'s' * (k != 1)} of the map." if k else ", no Python code.")]
    for a in r["areas"][:12]:
        out.append(f"  changed  {a['id']}  ({a['files']} file{'s' * (a['files'] != 1)}, +{a['plus']} -{a['minus']})"
                   + (": " + ", ".join(a["roles"][:5]) + (" ..." if len(a["roles"]) > 5 else "") if a["roles"] else ""))
    if len(r["areas"]) > 12:
        out.append(f"  ... and {len(r['areas']) - 12} more")
    if r["functions"]:
        sym = {"added": "+", "changed": "~", "removed": "-"}
        out.append("  functions " + ", ".join(f"{sym[u['status']]}{u['name']}" for u in r["functions"][:10]) + (" ..." if len(r["functions"]) > 10 else ""))
    if r["used_by"]:
        out.append("  used by  " + ", ".join(r["used_by"][:12]) + (" ..." if len(r["used_by"]) > 12 else "") + "  (may break)")
    if r["contract"]:
        out.append("CONTRACT BROKEN: other modules use these names and the change broke them")
        for c in r["contract"]:
            out.append(f"  {c['file']}::{c['name']} {c['change']}; used at " + ", ".join(c["users"][:4]) + (" ..." if len(c["users"]) > 4 else ""))
    else:
        out.append("contract: no name another module uses was changed or removed.")
    if r["new_dependencies"]:
        out.append("NEW DEPENDENCY: a part now uses a part it did not use before")
        for d in r["new_dependencies"]:
            out.append(f"  {d['from']} -> {d['to']}  ({d['at']})")
    if r["outside_fence"]:
        out.append("OUTSIDE THE FENCE: " + ", ".join(r["outside_fence"]))
    elif r["outside_fence"] is not None:
        out.append("fence: every change is inside it.")
    if r["blocked"]:
        out.append("blocked by the fence: " + ", ".join(r["blocked"][:8]))
    if r["map"] and (r["map"]["lines"] or r["map"]["unassigned"]):
        out.append(f"The modules (.mod/project.mod) are out of date: {len(r['map']['lines'])} line(s) match no file"
                   + (f" ({', '.join(r['map']['lines'][:3])})" if r["map"]["lines"] else "")
                   + f"; {len(r['map']['unassigned'])} code file(s) belong to no module"
                   + (f" ({', '.join(r['map']['unassigned'][:3])})" if r["map"]["unassigned"] else ""))
    if r["tests"]:
        out.append(f"tests to run ({len(r['tests'])}): " + " ".join(r["tests"][:10]) + (" ..." if len(r["tests"]) > 10 else ""))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modfence receipt", description="What a change touched and what it may break.")
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--since", default="HEAD", help="git revision to compare the working tree with (default HEAD)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook", action="store_true", help="run as a Claude Code Stop hook (reads its JSON on stdin)")
    ap.add_argument("--fleet", action="store_true", help="one receipt per git worktree, each against --base")
    ap.add_argument("--base", default="main", help="with --fleet: the branch every agent started from (default main)")
    a = ap.parse_args(argv)
    if a.hook:
        return hook(sys.stdin.read())
    if a.fleet:
        return fleet(a.project, a.base)
    try:
        r = build(a.project, a.since)
    except RuntimeError as e:
        print(f"modfence receipt: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=2) if a.json else text(r))
    return 0 if r["ok"] else 1


def hook(raw):
    """Stop hook (golden rule 5): block the first stop of a round that broke a contract, left the fence or added a
    cross-module dependency, with the receipt as the reason; let the second stop through. A project without
    MODULES.md, or outside git, is left alone: the hook runs in every project once the plugin is installed."""
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        event = {}
    if event.get("stop_hook_active"):
        return 0
    root = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        root = _git(root, "rev-parse", "--show-toplevel").decode().strip()
    except RuntimeError:
        return 0
    if modules.load(root) is None:
        return 0
    try:
        r = build(root)
    except Exception as e:  # a receipt that cannot be made never traps the agent
        print(f"modfence receipt skipped: {type(e).__name__}: {e}", file=sys.stderr)
        return 0
    if r["ok"]:
        return 0
    print(json.dumps({"decision": "block", "reason": text(r) + "\nFix these, or say why they are intended, then stop again."}))
    return 0


def worktrees(root):
    listing = _git(root, "worktree", "list", "--porcelain").decode("utf-8", "replace")
    return [line[len("worktree "):] for line in listing.splitlines() if line.startswith("worktree ")]


def fleet_list(root, base=None):
    """[{worktree, branch, ok, problems, parts, text}] for every git worktree (one agent each), against where it
    branched from `base` (default: the branch the project's own folder is on)."""
    base = base or _git(root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    out = []
    for wt in worktrees(root):
        try:
            since = _git(wt, "merge-base", "HEAD", base).decode().strip()
            branch = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
            r = build(wt, since)
        except RuntimeError as e:
            out.append({"worktree": wt, "branch": "?", "ok": None, "problems": [str(e)], "parts": [], "text": ""})
            continue
        problems = [f"{len(r['contract'])} contract break(s)"] * bool(r["contract"]) + \
                   [f"{len(r['new_dependencies'])} new dependency(ies)"] * bool(r["new_dependencies"]) + \
                   [f"{len(r['outside_fence'] or [])} outside the fence"] * bool(r["outside_fence"])
        out.append({"worktree": wt, "branch": branch, "ok": r["ok"], "problems": problems,
                    "parts": [a["id"] for a in r["areas"]], "text": text(r)})
    return out


def fleet(root, base="main"):
    """Golden rule 5, for many agents: one short receipt per git worktree (one agent each), against where it branched
    from `base`, so 10 to 100 agents' work is reviewed as modules, not as diffs. Exit 1 when any of them broke something."""
    try:
        agents = fleet_list(root, base)
    except RuntimeError as e:
        print(f"modfence receipt: {e}", file=sys.stderr)
        return 2
    for a in agents:
        print(f"== {a['branch']}  ({a['worktree']})  {'OK' if a['ok'] else 'CHECK: ' + ', '.join(a['problems'])}")
        print("\n".join("   " + line for line in a["text"].splitlines()[1:]))
    bad = sum(a["ok"] is False for a in agents)
    print(f"{len(agents)} worktree(s), {bad} to check. Cost per agent: N/A (modfence does not see the agents' bills).")
    return 1 if bad else 0
