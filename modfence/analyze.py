"""Build a module graph of a Python project. Every edge carries its receipts: the import lines it came from.

A module is a directory that holds source files; files directly under the project root form the module ".".
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


def module_of(path):
    d = os.path.dirname(path)
    return d if d else "."


def _resolve(parts, files):
    """The project file a dotted import refers to, trying the longest prefix first."""
    for n in range(len(parts), 0, -1):
        base = "/".join(parts[:n])
        for cand in (base + ".py", base + "/__init__.py"):
            for prefix in ("", "src/"):
                if prefix + cand in files:
                    return prefix + cand
    return None


def imports_of(path, tree, files):
    """[(target_file, line, source_text)] for imports that resolve to files in this project."""
    here = path.split("/")[:-1]
    found = []
    for node in ast.walk(tree):
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
            t = _resolve(parts, files)
            if t and t != path:
                found.append((t, node.lineno))
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


def analyze(root):
    """The full graph: modules, files and edges with receipts."""
    root = os.path.abspath(root)
    paths = walk(root)
    files = set(paths)
    mods, edges, fileinfo = {}, {}, {}
    for p in paths:
        full = os.path.join(root, p)
        text = read_text(full)
        lines = text.splitlines()
        info = {"path": p, "module": module_of(p), "lines": len(lines), "mtime": os.path.getmtime(full),
                "doc": "", "names": [], "error": None}
        try:
            tree = ast.parse(text, filename=p)
            doc = ast.get_docstring(tree) or ""
            info["doc"] = doc.strip().splitlines()[0] if doc.strip() else ""
            info["names"] = public_names(tree)
            for target, line in imports_of(p, tree, files):
                a, b = module_of(p), module_of(target)
                if a == b:
                    continue
                e = edges.setdefault((a, b), {"source": a, "target": b, "receipts": []})
                e["receipts"].append({"file": p, "line": line, "code": lines[line - 1].strip() if line <= len(lines) else "",
                                      "target_file": target})
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
        top = m["id"].split("/")[0]
        if top in ("tests", "test") or m["id"].endswith("/tests"):
            m["kind"] = "tests"
        if not m["doc"]:
            m["doc"] = next((fileinfo[f]["doc"] for f in m["files"] if fileinfo[f]["doc"]), "")
    return {"root": root, "name": os.path.basename(root), "modules": sorted(mods.values(), key=lambda m: m["id"]),
            "edges": sorted(edges.values(), key=lambda e: (e["source"], e["target"])), "files": fileinfo,
            "analyzed_at": time.time()}


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
