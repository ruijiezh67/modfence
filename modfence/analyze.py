"""Build a module graph of a Python project. Every edge carries its receipts: the import lines it came from.

A module is a directory that holds source files. Flat code is split: a .py file directly under the project root,
or in a directory with SPLIT_AT or more .py files of its own (nanochat/gpt.py, nanochat/engine.py ...), is a module
of its own. Other root files belong to the module ".".
An edge A -> B exists when a file in A imports a file in B. Nothing here asks a model: the graph is what the
code says, so a node or an edge can always be traced back to a file and a line.
"""
import ast, hashlib, os, time


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


def _resolve(parts, files):
    """(project file, parts used) for a dotted import, trying the longest prefix first; (None, 0) if not ours."""
    for n in range(len(parts), 0, -1):
        base = "/".join(parts[:n])
        for cand in (base + ".py", base + "/__init__.py"):
            for prefix in ("", "src/"):
                if prefix + cand in files:
                    return prefix + cand, n
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
        for parts in targets:
            t, used = _resolve(parts, files)
            if t and t != path:
                name = parts[-1] if isinstance(node, ast.ImportFrom) and used == len(parts) - 1 and parts[-1] != "*" else None
                found.append((t, node.lineno, name))
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


def analyze(root):
    """The full graph: modules, files and edges with receipts."""
    root = os.path.abspath(root)
    paths = walk(root)
    files = set(paths)
    split = split_dirs(paths)
    mods, edges, fileinfo = {}, {}, {}
    for p in paths:
        full = os.path.join(root, p)
        text = read_text(full)
        lines = text.splitlines()
        info = {"path": p, "module": module_of(p, split), "lines": len(lines), "mtime": os.path.getmtime(full),
                "doc": "", "names": [], "error": None}
        try:
            tree = ast.parse(text, filename=p)
            doc = ast.get_docstring(tree) or ""
            info["doc"] = doc.strip().splitlines()[0] if doc.strip() else ""
            info["names"] = public_names(tree)
            for target, line, name in imports_of(p, tree, files):
                a, b = module_of(p, split), module_of(target, split)
                if a == b:
                    continue
                e = edges.setdefault((a, b), {"source": a, "target": b, "receipts": []})
                e["receipts"].append({"file": p, "line": line, "code": lines[line - 1].strip() if line <= len(lines) else "",
                                      "target_file": target, "name": name})
        except SyntaxError as ex:
            info["error"] = f"SyntaxError line {ex.lineno}: {ex.msg}"
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


def snapshot(root):
    """{relative path: sha1} of every file in the project (any type), for before/after diffs of a run."""
    root = os.path.abspath(root)
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            full = os.path.join(d, f)
            try:
                if os.path.getsize(full) > SNAPSHOT_MAX_BYTES:
                    continue
                out[os.path.relpath(full, root).replace(os.sep, "/")] = hashlib.sha1(read_bytes(full)).hexdigest()
            except OSError:
                pass
    return out


def snapshot_bytes(root, budget=50_000_000):
    """{relative path: bytes} for files up to SNAPSHOT_MAX_BYTES each and `budget` in total, smallest first.
    Files beyond the budget are left out; changes to them can be shown but not reverted."""
    root = os.path.abspath(root)
    sizes = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            full = os.path.join(d, f)
            try:
                n = os.path.getsize(full)
            except OSError:
                continue
            if n <= SNAPSHOT_MAX_BYTES:
                sizes.append((n, os.path.relpath(full, root).replace(os.sep, "/")))
    out, used = {}, 0
    for n, rel in sorted(sizes):
        if used + n > budget:
            break
        try:
            out[rel] = read_bytes(os.path.join(root, rel))
            used += n
        except OSError:
            pass
    return out


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
