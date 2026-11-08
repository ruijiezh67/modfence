"""Build a module graph of a Python project. Every edge carries its receipts: the import lines it came from.

A module is a directory that holds source files. Flat code is split: a .py file directly under the project root,
or in a directory with SPLIT_AT or more .py files of its own (nanochat/gpt.py, nanochat/engine.py ...), is a module
of its own. Other root files belong to the module ".".
An edge A -> B exists when a file in A imports a file in B. Nothing here asks a model: the graph is what the
code says, so a node or an edge can always be traced back to a file and a line.
"""
import ast, builtins, hashlib, os, threading, time
from collections import Counter


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()

SKIP_DIRS = {".git", ".modfence", "__pycache__", ".venv", "venv", "env", "node_modules", "build", "dist",
             ".claude", ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}
SNAPSHOT_MAX_BYTES = 2_000_000


def walk(root, exts=(".py",)):
    """Relative POSIX paths of source files under root, sorted."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in files:
            if f.endswith(exts):
                out.append(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return sorted(out)


SPLIT_AT = 8


def _is_tests(d):
    return d.split("/")[0] in ("tests", "test") or d.endswith("/tests")


def split_dirs(paths):
    """Directories so flat that each of their .py files becomes a module (tests stay one module)."""
    count = {}
    for p in paths:
        d = os.path.dirname(p)
        if p.endswith(".py") and os.path.basename(p) != "__init__.py":
            count[d] = count.get(d, 0) + 1
    return {d for d, n in count.items() if d and n >= SPLIT_AT and not _is_tests(d)}


def module_of(path, split=()):
    d = os.path.dirname(path)
    if d and (d not in split or not path.endswith(".py") or os.path.basename(path) == "__init__.py"):
        return d
    return path if path.endswith(".py") else "."


def _resolve(parts, files, here=()):
    """(project file, parts used) for a dotted import, trying the longest prefix first; (None, 0) if not ours.
    Import roots tried, shallowest first: the project root, src/, then each directory above the importing file,
    because big projects often run from a subfolder (backend/ on sys.path, so `kernel.x` is backend/kernel/x.py)."""
    roots = ["", "src/"] + ["/".join(here[:k]) + "/" for k in range(1, len(here) + 1)]
    for n in range(len(parts), 0, -1):
        base = "/".join(parts[:n])
        for prefix in roots:
            for cand in (prefix + base + ".py", prefix + base + "/__init__.py"):
                if cand in files:
                    return cand, n
    return None, 0


_BODIES = ("body", "orelse", "finalbody", "handlers", "cases")


def _statements(tree):
    """Every statement, at any depth (inside functions, if, try, with, match ...). Imports are statements, so
    skipping expressions finds the same imports as ast.walk at a fraction of the cost."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for field in reversed(_BODIES):  # reversed pushes keep source order when popped
            stack.extend(reversed(getattr(node, field, None) or ()))


def imports_of(path, tree, files):
    """[(target_file, line, name)] for imports that resolve to files in this project. name is what `from x import
    name` took from the file (a function, class ...), or None when the import names a module."""
    return [(t, line, name) for t, line, name, _ in _resolved(path, [s + ("",) for s in import_specs(path, tree)], files)]


def _resolved(path, specs, files):
    found = []
    for parts, line, is_from, code in specs:
        t, used = _resolve(parts, files, path.split("/")[:-1])
        if t and t != path:
            name = parts[-1] if is_from and used == len(parts) - 1 and parts[-1] != "*" else None
            found.append((t, line, name, code))
    return found


def import_specs(path, tree):
    """[(dotted parts, line, is_from)] for every import statement, before resolving against the project's files."""
    here = path.split("/")[:-1]
    found = []
    for node in _statements(tree):
        targets = []
        if isinstance(node, ast.Import):
            targets = [a.name.split(".") for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: from ..x import y
                base = here[: len(here) - (node.level - 1)] if node.level > 1 else here
                mod = base + (node.module.split(".") if node.module else [])
            else:
                mod = node.module.split(".") if node.module else []
            targets = [mod + [a.name] for a in node.names] or [mod]
        found += [(parts, node.lineno, isinstance(node, ast.ImportFrom)) for parts in targets]
    return found


def public_names(tree):
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            names.append({"name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "def", "line": node.lineno})
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_"):
                    names.append({"name": t.id, "kind": "const", "line": node.lineno})
    return names


def _args(node):
    a = node.args
    names = [x.arg for x in a.posonlyargs + a.args]
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    names += ["*" + a.vararg.arg] if a.vararg else []
    names += [x.arg for x in a.kwonlyargs]
    names += ["**" + a.kwarg.arg] if a.kwarg else []
    return ", ".join(names)


def functions(tree, lines):
    """The units a person reads instead of lines: top-level functions, classes and UPPER_CASE constants, and the methods
    of those classes.
    sha fingerprints a unit's own lines (a class without its methods), so a run's changes can be named per function."""
    out = []
    fdef = (ast.FunctionDef, ast.AsyncFunctionDef)

    def add(node, name, kind, skip=()):
        own = [l for i, l in enumerate(lines[node.lineno - 1:node.end_lineno], node.lineno)
               if l.strip() and not any(a <= i <= b for a, b in skip)]  # blank lines are not a change
        doc = "" if kind == "const" else (ast.get_docstring(node) or "").strip()
        out.append({"name": name, "kind": kind, "line": node.lineno, "end": node.end_lineno,
                    "args": _args(node) if kind in ("def", "method") else "",
                    "doc": doc.splitlines()[0] if doc else "",
                    "sha": hashlib.sha1("\n".join(own).encode("utf-8")).hexdigest()[:12]})
    for node in tree.body:
        if isinstance(node, fdef):
            add(node, node.name, "def")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):  # module constants (SYMBOLS = {...}) are units too
            names = [t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                     if isinstance(t, ast.Name) and t.id.isupper()]
            if len(names) == 1:
                add(node, names[0], "const")
        elif isinstance(node, ast.ClassDef):
            subs = [s for s in node.body if isinstance(s, fdef)]
            add(node, node.name, "class", [(s.lineno, s.end_lineno) for s in subs])
            for s in subs:
                add(s, f"{node.name}.{s.name}", "method")
    return out


def function_changes(before, after):
    """[{name, kind, status}] for units added, changed or removed between two versions (bytes or None) of a .py file;
    None when either version does not parse. A change outside every unit is reported as the unit "(module level)"."""
    def units(data):
        if data is None:
            return {}
        text = data.decode("utf-8")
        lines, tree = text.splitlines(), ast.parse(text)
        out = {f["name"]: f for f in functions(tree, lines)}
        spans = [(f["line"], f["end"]) for f in out.values() if f["kind"] != "method"]
        rest = [l for i, l in enumerate(lines, 1) if l.strip() and not any(a <= i <= b for a, b in spans)]
        out["(module level)"] = {"kind": "code", "sha": hashlib.sha1("\n".join(rest).encode("utf-8")).hexdigest()}
        return out
    try:
        a, b = units(before), units(after)
    except (UnicodeDecodeError, SyntaxError, ValueError):
        return None
    if before is None or after is None:  # a whole file added or removed: its units, not its module-level code
        a.pop("(module level)", None), b.pop("(module level)", None)
    out = [{"name": n, "kind": b[n]["kind"], "status": "added"} for n in b if n not in a]
    out += [{"name": n, "kind": b[n]["kind"], "status": "changed"} for n in b if n in a and a[n]["sha"] != b[n]["sha"]]
    out += [{"name": n, "kind": a[n]["kind"], "status": "removed"} for n in a if n not in b]
    return out


_PARSED = {}  # full path -> ((size, mtime_ns), parsed). ponytail: never evicted; one entry per .py file seen


def _parse(full, p):
    """What analyze needs from one file. Cached until the file's size or mtime changes, so re-analyzing a big
    project after a run only parses the files the run touched."""
    st = os.stat(full)
    key = (st.st_size, st.st_mtime_ns)
    hit = _PARSED.get(full)
    if hit and hit[0] == key:
        return hit[1]
    text = read_text(full)
    lines = text.splitlines()
    r = {"lines": len(lines), "mtime": st.st_mtime, "doc": "", "names": [], "error": None, "imports": []}
    try:
        tree = ast.parse(text, filename=p)
        doc = ast.get_docstring(tree) or ""
        r["doc"] = doc.strip().splitlines()[0] if doc.strip() else ""
        r["names"] = public_names(tree)
        r["imports"] = [(parts, line, is_from, lines[line - 1].strip() if line <= len(lines) else "")
                        for parts, line, is_from in import_specs(p, tree)]
    except SyntaxError as ex:
        r["error"] = f"SyntaxError line {ex.lineno}: {ex.msg}"
    _PARSED[full] = (key, r)
    return r


def analyze(root):
    """The full graph: modules, files and edges with receipts."""
    root = os.path.abspath(root)
    paths = walk(root)
    files = set(paths)
    split = split_dirs(paths)
    mods, edges, fileinfo = {}, {}, {}
    for p in paths:
        r = _parse(os.path.join(root, p), p)
        info = {"path": p, "module": module_of(p, split), "lines": r["lines"], "mtime": r["mtime"],
                "doc": r["doc"], "names": r["names"], "error": r["error"]}
        for target, line, name, code in _resolved(p, r["imports"], files):
            a, b = module_of(p, split), module_of(target, split)
            if a == b:
                continue
            e = edges.setdefault((a, b), {"source": a, "target": b, "receipts": []})
            e["receipts"].append({"file": p, "line": line, "code": code, "target_file": target, "name": name})
        fileinfo[p] = info
        m = mods.setdefault(info["module"], {"id": info["module"], "files": [], "lines": 0, "names": [], "doc": "",
                                            "mtime": 0, "kind": "module"})
        m["files"].append(p)
        m["lines"] += info["lines"]
        m["mtime"] = max(m["mtime"], info["mtime"])
        if p.endswith("__init__.py") and info["doc"]:
            m["doc"] = info["doc"]
        m["names"] += [dict(n, file=p) for n in info["names"]]
    for m in mods.values():
        if _is_tests(m["id"]):
            m["kind"] = "tests"
        if not m["doc"]:
            m["doc"] = next((fileinfo[f]["doc"] for f in m["files"] if fileinfo[f]["doc"]), "")
    return {"root": root, "name": os.path.basename(root), "modules": sorted(mods.values(), key=lambda m: m["id"]),
            "edges": sorted(edges.values(), key=lambda e: (e["source"], e["target"])), "files": fileinfo,
            "split": sorted(split), "analyzed_at": time.time()}


_SNAP, _SNAP_LOCK = {}, threading.Lock()  # root -> {rel: (size, mtime_ns, sha1, bytes or None)}


def snapshot(root, budget=50_000_000):
    """{relative path: sha1} of every file in the project (any type) up to SNAPSHOT_MAX_BYTES, for before/after
    diffs of a run. A file is read again only when its size or mtime changed since the last call for this root, so
    a warm snapshot of a big project is one directory walk. The bytes of up to `budget` of the files are kept for
    snapshot_bytes, so a run's changes can be reverted; files beyond it can be shown but not reverted.
    ponytail: (size, mtime) is the change test, as in make and rsync; a same-size edit in the same mtime tick is missed."""
    root = os.path.abspath(root)
    with _SNAP_LOCK:
        old, new, used = _SNAP.get(root, {}), {}, 0
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in files:
                full = os.path.join(d, f)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                try:
                    st = os.stat(full)
                    if st.st_size > SNAPSHOT_MAX_BYTES:
                        continue
                    hit = old.get(rel)
                    fresh = hit and hit[:2] == (st.st_size, st.st_mtime_ns)
                    data = hit[3] if fresh else None
                    if data is None and (not fresh or used + st.st_size <= budget):
                        data = read_bytes(full)
                    sha = hit[2] if fresh else hashlib.sha1(data).hexdigest()
                except OSError:
                    continue
                if data is not None and used + len(data) > budget:
                    data = None
                used += len(data or b"")
                new[rel] = (st.st_size, st.st_mtime_ns, sha, data)
        _SNAP[root] = new
        return {k: v[2] for k, v in new.items()}


def snapshot_bytes(root):
    """{relative path: bytes} kept by the last snapshot(root)."""
    with _SNAP_LOCK:
        return {k: v[3] for k, v in _SNAP.get(os.path.abspath(root), {}).items() if v[3] is not None}


def diff(before, after):
    """(added, modified, deleted) relative paths."""
    added = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    return added, modified, deleted


def dependents(graph, module_ids):
    """Modules that import any of module_ids, directly or transitively: the ripple of a change."""
    rev = {}
    for e in graph["edges"]:
        rev.setdefault(e["target"], set()).add(e["source"])
    seen, todo = set(), list(module_ids)
    while todo:
        m = todo.pop()
        for s in rev.get(m, ()):
            if s not in seen and s not in module_ids:
                seen.add(s)
                todo.append(s)
    return sorted(seen)


def call_graph(root, files, allfiles):
    """How the top-level functions and classes of `files` use each other: calls (a method's calls count for its class),
    and base classes. Found by name from the code, so it is approximate: calls through variables, getattr and duck
    typing are missed. Returns {"nodes": [...], "edges": [...], "boundary": [...], "calls": n, "resolved": n}.
    Node ids are "path::Name"; a boundary node is another project file the code calls into."""
    files = list(files)
    keep = set(files)
    nodes, edges, boundary, calls, resolved = [], Counter(), Counter(), 0, 0
    tops = {}
    trees = {}
    for f in files:
        text = read_text(os.path.join(root, f))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        trees[f] = tree
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                tops[(f, node.name)] = f"{f}::{node.name}"
                doc = (ast.get_docstring(node) or "").strip()
                nodes.append({"id": f"{f}::{node.name}", "name": node.name, "file": f, "line": node.lineno,
                              "kind": "class" if isinstance(node, ast.ClassDef) else "def",
                              "lines": node.end_lineno - node.lineno + 1, "doc": doc.splitlines()[0] if doc else ""})
    for f, tree in trees.items():
        imported = {}  # local name -> target file, for `from x import name`
        for parts, _line, is_from in import_specs(f, tree):
            t, used = _resolve(parts, allfiles, f.split("/")[:-1])
            if t and is_from and used == len(parts) - 1:
                imported[parts[-1]] = t
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            src = f"{f}::{node.name}"
            targets = []
            if isinstance(node, ast.ClassDef):
                targets += [(b.id, "inherits") for b in node.bases if isinstance(b, ast.Name)]
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    calls += 1
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        if hasattr(builtins, fn.id):  # print(), len() ... are not project code
                            calls -= 1
                            continue
                        targets.append((fn.id, "calls"))
                    elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in imported:
                        targets.append((fn.value.id, "calls"))  # SomeClass.create(), imported module objects
                    else:
                        continue
            for name, kind in targets:
                if (f, name) in tops:
                    dst = tops[(f, name)]
                elif name in imported:
                    t = imported[name]
                    dst = tops.get((t, name)) if t in keep else None
                    if dst is None:
                        boundary[(src, t, kind)] += 1
                        resolved += kind == "calls"
                        continue
                else:
                    continue
                resolved += kind == "calls"
                if dst != src:
                    edges[(src, dst, kind)] += 1
    return {"nodes": nodes, "edges": [{"source": a, "target": b, "kind": k, "count": n} for (a, b, k), n in sorted(edges.items())],
            "boundary": [{"source": a, "file": t, "kind": k, "count": n} for (a, t, k), n in sorted(boundary.items())],
            "calls": calls, "resolved": resolved}
