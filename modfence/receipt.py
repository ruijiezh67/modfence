"""modfence receipt: what a change touched and what it may break, from git, with no UI and no model (golden rule 7).

    modfence receipt [PROJECT] [--since REV] [--json]

Compares the working tree with REV (default HEAD), untracked files included, whichever agent or person made the change:
- the modules it changed, with the lines added and removed;
- the modules that use them, which the change may break;
- contract breaks: names another module uses whose signature changed or that went away, with the lines that use them;
- the files changed outside the fence, when one is set (.modfence/fence.json);
- the test files that cover the changed modules and their users.
Exit status 1 when a contract broke or a file outside the fence changed, so a hook or CI can block on it; 0 otherwise;
2 when PROJECT is not a git work tree.
"""
import argparse, json, os, subprocess, sys

from . import analyze, brief, roles, runner, scope_guard

SKIP = (".modfence/", ".claude/")


def _git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip())
    return r.stdout


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
    # The map's own level (golden rule 2): the areas and roles of the project, when it has them, else the modules.
    store = roles.load_store(root) or {}
    role_area = {r: a for a, v in (store.get("areas") or {}).items() for r in v.get("roles", [])}
    name = lambda d, k: ((store.get(d) or {}).get(k) or {}).get("name")
    place = lambda path: (name("areas", role_area.get((store.get("files") or {}).get(path))), name("roles", (store.get("files") or {}).get(path)))
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
                    None if f["status"] == "deleted" else open(os.path.join(root, f["path"]), "rb").read())
        for f in py if f["status"] != "added"})
    fence = scope_guard.load_fence(root)
    outside = [f["path"] for f in files if not scope_guard.allowed(f["path"], root, fence[1])] if fence else None
    tests = runner.select_tests(graph, [f["path"] for f in py]) if py else None
    return {"since": since, "files": files, "modules": [{"id": m, **mods[m]} for m in changed], "users": users,
            "areas": sorted(areas.values(), key=lambda a: -(a["plus"] + a["minus"])), "used_by": used_areas,
            "contract": contract, "outside_fence": outside, "tests": tests["files"] if tests else [],
            "ok": not contract and not outside}


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
    if r["used_by"]:
        out.append("  used by  " + ", ".join(r["used_by"][:12]) + (" ..." if len(r["used_by"]) > 12 else "") + "  (may break)")
    if r["contract"]:
        out.append("CONTRACT BROKEN: other modules use these names and the change broke them")
        for c in r["contract"]:
            out.append(f"  {c['file']}::{c['name']} {c['change']}; used at " + ", ".join(c["users"][:4]) + (" ..." if len(c["users"]) > 4 else ""))
    else:
        out.append("contract: no name another module uses was changed or removed.")
    if r["outside_fence"]:
        out.append("OUTSIDE THE FENCE: " + ", ".join(r["outside_fence"]))
    elif r["outside_fence"] is not None:
        out.append("fence: every change is inside it.")
    if r["tests"]:
        out.append(f"tests to run ({len(r['tests'])}): " + " ".join(r["tests"][:10]) + (" ..." if len(r["tests"]) > 10 else ""))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modfence receipt", description="What a change touched and what it may break.")
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--since", default="HEAD", help="git revision to compare the working tree with (default HEAD)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = build(a.project, a.since)
    except RuntimeError as e:
        print(f"modfence receipt: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=2) if a.json else text(r))
    return 0 if r["ok"] else 1
