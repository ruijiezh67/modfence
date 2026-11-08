"""The AI-only brief of a fence (golden rules 1, 4 and 6).

During a sealed run the agent cannot read code outside its fence. This brief is all it sees of the rest of the project.
It is built from the import graph's receipts and Python's ast, with no model call, and holds three things:

- deps: for each module the fence imports from, only the names it uses, as one-line stubs (Agentless-style skeletons);
- contract: the fence's names that other modules use, with who uses them (the fence must keep these working);
- near: one line per neighbouring module (one hop, after RepoGraph: two hops measured worse).

It is written for the model, not for people. ENCODINGS gives three renderings of the same facts; the one that ships
(DEFAULT) is decided by measurement, see bench/brief_probe.py.
"""
import ast, os
from collections import defaultdict

from . import analyze



def _units(root, path):
    """{name: unit} for a file's functions, classes and constants (analyze.functions), or {} when it does not parse."""
    try:
        text = analyze.read_text(os.path.join(root, path))
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return {}
    units = {u["name"]: u for u in analyze.functions(tree, text.splitlines())}
    for node in tree.body:  # a class's annotated fields (dataclasses, NamedTuple) are part of its interface
        if isinstance(node, ast.ClassDef) and node.name in units:
            units[node.name]["fields"] = [x.target.id for x in node.body if isinstance(x, ast.AnnAssign) and isinstance(x.target, ast.Name)]
    return units


def _stub(u, methods=()):
    """One line a model reads as an interface: `def f(a, b)  # doc` or `class C: m(x) n()  # doc`."""
    if u is None:
        return None
    doc = f"  # {u['doc'][:80]}" if u.get("doc") else ""
    if u["kind"] == "class":
        pub = [m for m in methods if not m["name"].split(".")[-1].startswith("_")]
        ms = " ".join(f"{m['name'].split('.')[-1]}({m['args']})" for m in pub[:8]) + (f" +{len(pub) - 8} more" if len(pub) > 8 else "")
        fs = f"({', '.join(u['fields'])})" if u.get("fields") else ""
        return f"class {u['name']}{fs}:{(' ' + ms) if ms else ''}{doc}"
    if u["kind"] == "const":
        return f"{u['name']} = ..."
    return f"def {u['name']}({u['args']}){doc}"


def file_stub(root, path, limit=12):
    """The public face of one file, as stub lines: what a denied Read gets back instead of the file."""
    units = _units(root, path)
    tops = [u for n, u in units.items() if "." not in n and not n.startswith("_") and n != "(module level)"]
    methods = defaultdict(list)
    for n, u in units.items():
        if u["kind"] == "method":
            methods[n.split(".")[0]].append(u)
    lines = [_stub(u, methods.get(u["name"], ())) for u in tops[:limit]]
    return lines + ([f"... {len(tops) - limit} more"] if len(tops) > limit else [])


def scope_files(graph, scope):
    """Fence entries (module ids, file paths, file::function) as the set of files they cover."""
    mods = {m["id"]: m for m in graph["modules"]}
    out = set()
    for s in scope:
        s = s.split("::")[0]
        out.update(mods[s]["files"] if s in mods else [s] if s in graph["files"] else [])
    return out


def facts(graph, scope):
    """What the brief says, before rendering: {"fence", "deps", "contract", "near", "others"}. deps and contract are
    lists ordered by importance (how many import lines use a name), so a budget can keep the head and name the tail."""
    tests = {m["id"] for m in graph["modules"] if m["kind"] == "tests"}
    root, mine = graph["root"], scope_files(graph, [s for s in scope if s not in tests])  # tests: editable, not briefed
    mod_of = {f: i["module"] for f, i in graph["files"].items()}
    docs = {m["id"]: m["doc"] for m in graph["modules"]}
    used = defaultdict(lambda: defaultdict(int))   # (module, target file) -> name -> uses in the fence
    users = defaultdict(lambda: defaultdict(list))  # fence file -> name -> [user file:line]
    for e in graph["edges"]:
        for r in e["receipts"]:
            a, b = r["file"] in mine, r["target_file"] in mine
            names = [(r["name"], r["line"])] if r["name"] else attr_uses(root, r) or [(None, r["line"])]  # mod.f() counts as f
            for n, line in names:
                if a and not b:
                    used[(mod_of[r["target_file"]], r["target_file"])][n] += 1  # None: the whole module, no attribute seen
                elif b and not a:
                    users[r["target_file"]][n or "(module)"].append(f"{r['file']}:{line}")
    deps = []
    for (m, f), names in used.items():
        units = _units(root, f)
        methods = defaultdict(list)
        for n, u in units.items():
            if u["kind"] == "method":
                methods[n.split(".")[0]].append(u)
        for n, c in names.items():
            stub = (_stub(units.get(n), methods.get(n, ())) or f"{n} = ...  # re-export or variable") if n else                 f"{os.path.basename(f)}: " + ", ".join(_name(l) for l in file_stub(root, f, 8))
            deps.append({"mod": m, "name": n or os.path.basename(f), "stub": stub, "n": c})
    deps.sort(key=lambda d: (-d["n"], d["mod"], d["name"]))
    contract = []
    for f in users:
        units = _units(root, f)
        for n, us in users[f].items():
            u = units.get(n)
            contract.append({"name": n, "file": f, "stub": _stub(u) if u else n, "users": sorted(set(us)),
                             "mods": sorted({mod_of[x.rsplit(":", 1)[0]] for x in us})})
    contract.sort(key=lambda c: (-len(c["users"]), c["file"], c["name"]))
    fence_mods = {mod_of[f] for f in mine}
    near = sorted({e["target"] for e in graph["edges"] if e["source"] in fence_mods} |
                  {e["source"] for e in graph["edges"] if e["target"] in fence_mods} - fence_mods)
    return {"fence": sorted(mine), "deps": deps, "contract": contract, "near": {m: docs.get(m, "") for m in near},
            "others": len(graph["modules"]) - len(fence_mods) - len(near)}


BUDGET = 6000  # characters, about 1.5k tokens (the survey's cap); past it, names only. Measured, not guessed: see bench


def _fit(items, line, budget):
    """Split items into (full lines, names only) so the full lines fit the budget; order is importance."""
    full, rest, used = [], [], 0
    for it in items:
        l = line(it)
        if used + len(l) + 1 <= budget:
            full.append((it, l)); used += len(l) + 1
        else:
            rest.append(it)
    return full, rest


def _grouped(full, rest, head):
    """Render by module: full lines, then the names that did not fit."""
    by, tail = defaultdict(list), defaultdict(list)
    for it, l in full:
        by[it["mod"]].append(l)
    for it in rest:
        tail[it["mod"]].append(it["name"])
    out = []
    for m in sorted(set(by) | set(tail)):
        out.append(head(m))
        out += ["  " + l for l in by[m]]
        if tail[m]:
            out.append("  also: " + ", ".join(sorted(tail[m])))
    return out


def render_sig(f, budget=BUDGET):
    """Readable stubs: the default until measurement says otherwise."""
    full, rest = _fit(f["deps"], lambda d: d["stub"], budget * 3 // 5)
    out = ["## What the fence uses from other modules (their code is hidden from you; these are the interfaces)"] + _grouped(full, rest, lambda m: m + ":")
    if f["contract"]:
        out.append("## The fence's contract (other modules use these; keep their names and parameters working)")
        cfull, crest = _fit(f["contract"], lambda c: f"{_terse(c['stub'])}  <- {_few(c['mods'])}", budget // 4)
        out += [l for _, l in cfull] + (["also used: " + ", ".join(c["name"] for c in crest)] if crest else [])
    told = {d["mod"] for d in f["deps"]} | {m for c in f["contract"] for m in c["mods"]}
    left = [m for m in f["near"] if m not in told]
    if left:
        out.append("## Also connected: " + _few(left, 8))
    if f["others"] > 0:
        out.append(f"({f['others']} more modules, not connected to the fence)")
    return "\n".join(out)


def _few(xs, n=4):
    return ", ".join(xs[:n]) + (f" +{len(xs) - n} more" if len(xs) > n else "")


def _terse(line):
    """`class C(a, b): m(x)  # doc` -> `C{a,b}.m(x)`; `def f(x)  # doc` -> `f(x)`."""
    line = line.split("  # ")[0]
    if line.startswith("class "):
        head, _, ms = line[6:].partition(":")
        name, _, fields = head.partition("(")
        return name + ("{" + fields.rstrip(")").replace(", ", ",") + "}" if fields else "") + "".join("." + m for m in ms.split())
    return line.replace("def ", "")


def _name(line):
    line = line.split("  # ")[0].replace("def ", "").replace("class ", "")
    return line.split("(")[0].split(":")[0].split(" =")[0]


def render_ids(f, budget=BUDGET):
    """Compressed: modules as short ids, no prose, no docs. For the model only."""
    mods = sorted({d["mod"] for d in f["deps"]} | {m for c in f["contract"] for m in c["mods"]} | set(f["near"]))
    ids = {m: f"M{i}" for i, m in enumerate(mods)}
    full, rest = _fit(f["deps"], lambda d: _terse(d["stub"]), budget * 3 // 5)
    out = ["MODS " + " ".join(f"{v}={k}" for k, v in ids.items())]
    out += _grouped(full, rest, lambda m: "USE " + ids[m])
    cfull, crest = _fit(f["contract"], lambda c: f"KEEP {_terse(c['stub'])} <" + ",".join(ids[m] for m in c["mods"]), budget // 4)
    out += [l for _, l in cfull] + (["KEEP " + ",".join(c["name"] for c in crest)] if crest else [])
    return "\n".join(out)


def render_iface(f, budget=BUDGET):
    """Smallest: names only, no signatures, no neighbours."""
    by = defaultdict(list)
    for d in f["deps"]:
        by[d["mod"]].append(d["name"])
    out = [f"uses from {m}: " + ", ".join(sorted(ns)) for m, ns in sorted(by.items())]
    if f["contract"]:
        out.append("others use (keep working): " + ", ".join(c["name"] for c in f["contract"]))
    return "\n".join(out)[:budget]


ENCODINGS = {"sig": render_sig, "ids": render_ids, "iface": render_iface}
# Chosen by bench/brief_probe.py (Haiku, 7 fences, 88 questions with known answers): ids 88/88 at 0.3-0.9x the size of
# sig (82/88); iface 39/88. See docs/EVALUATION.md section 5.
DEFAULT = "ids"
LEGEND = {"ids": "Brief format: MODS maps short ids to modules. USE Mx lists what the fence uses from module Mx: f(params), "
                 "Class{fields}.method(params), NAME = ... for variables; 'also:' names had no room. KEEP lists the fence's "
                 "names other modules use (<ids of the users): keep their names and parameters working.",
          "sig": "", "iface": ""}


def brief(graph, scope, encoding=DEFAULT, budget=BUDGET):
    return ENCODINGS[encoding](facts(graph, scope), budget)


def show(root, name):
    """The escape hatch (show.py): a file's stubs, or one name's stub and full docstring; never a body."""
    path, _, n = name.partition("::")
    if not n:
        return "\n".join(file_stub(root, path, 40)) or f"{path}: nothing public"
    u = _units(root, path).get(n)
    if not u:
        return f"{path}::{n}: not found"
    try:
        tree = ast.parse(analyze.read_text(os.path.join(root, path)))
        node = next(x for x in ast.walk(tree) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and x.name == n.split(".")[-1] and x.lineno == u["line"])
        doc = ast.get_docstring(node) or ""
    except (StopIteration, SyntaxError, OSError):
        doc = ""
    return _stub(u) + (f'\n"""{doc}"""' if doc else "")


# ---------- the contract across a run (golden rule 3): did a run break what other modules use? ----------
def _params(fn):
    """[(name, kind, required, default source)] for a def, self/cls dropped."""
    a, out = fn.args, []
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for i, (x, d) in enumerate(zip(pos, defaults)):
        if i == 0 and x.arg in ("self", "cls"):
            continue
        out.append((x.arg, "positional", d is None, ast.unparse(d) if d is not None else None))
    if a.vararg:
        out.append(("*" + a.vararg.arg, "var", False, None))
    for x, d in zip(a.kwonlyargs, a.kw_defaults):
        out.append((x.arg, "keyword", d is None, ast.unparse(d) if d is not None else None))
    if a.kwarg:
        out.append(("**" + a.kwarg.arg, "var", False, None))
    return out


def _top_statements(body):
    """Module-level statements, also inside if/try/with blocks (`if TYPE_CHECKING:`, `try: import x`), not in defs."""
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)) or type(node).__name__ == "TryStar":
            for part in (getattr(node, "body", []), getattr(node, "orelse", []), getattr(node, "finalbody", []),
                         *[h.body for h in getattr(node, "handlers", [])]):
                yield from _top_statements(part)


def _base(b):
    """A base class by name: `MutableMapping[str, T]` and `typing.MutableMapping` are both MutableMapping."""
    if isinstance(b, ast.Subscript):
        b = b.value
    name = ast.unparse(b).split(".")[-1]
    return name.lower() if name in _TYPING_ALIASES else name  # typing.List[T] and list[T] are the same base


_TYPING_ALIASES = {"List", "Dict", "Set", "FrozenSet", "Tuple", "Type", "DefaultDict", "OrderedDict", "Deque"}


_RECORDS = ("dataclass", "define", "frozen", "attrs", "NamedTuple", "TypedDict")  # classes whose fields are parameters


def signatures(data):
    """{top-level name: {"kind", "params", "bases"}} from a file's bytes; None when it does not parse. A class's params
    are its __init__'s; a dataclass-like class's are its annotated fields; otherwise unknown (None), since annotations
    on a plain class are not constructor parameters. Imported or assigned names are "name" kind."""
    if data is None:
        return {}
    try:
        tree = ast.parse(data.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError, ValueError):
        return None
    out = {}
    for node in _top_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, {"kind": "def", "params": _params(node), "bases": []})
        elif isinstance(node, ast.ClassDef):
            init = next((x for x in node.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == "__init__"), None)
            record = any(k in ast.unparse(x) for x in node.decorator_list + node.bases for k in _RECORDS)
            fields = [(x.target.id, "keyword", x.value is None, ast.unparse(x.value) if x.value is not None else None)
                      for x in node.body if isinstance(x, ast.AnnAssign) and isinstance(x.target, ast.Name)]
            out.setdefault(node.name, {"kind": "class", "params": _params(init) if init else fields if record else None,
                                       "bases": [_base(b) for b in node.bases]})
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.setdefault((a.asname or a.name).split(".")[0], {"kind": "name", "params": None, "bases": []})
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, {"kind": "name", "params": None, "bases": []})
    return out


def breaks(old, new):
    """What changed in one name's contract, in the spirit of griffe's breakage kinds; [] when nothing a caller relies
    on changed. old/new: entries of signatures(); new None means the name is gone."""
    if new is None:
        return ["removed"]
    if old["kind"] != new["kind"] and "name" not in (old["kind"], new["kind"]):
        return [f"was a {old['kind']}, now a {new['kind']}"]
    out = [f"base {b} removed" for b in old["bases"] if b not in new["bases"]]
    if old["params"] is None or new["params"] is None:
        return out
    np = {p[0]: (i, p) for i, p in enumerate(new["params"])}
    takes_any = any(p[0].startswith("**") for p in new["params"])
    for i, (name, kind, req, default) in enumerate(old["params"]):
        if name.startswith("*"):
            if name not in np:
                out.append(f"{name} removed")
            continue
        if name not in np:
            if not takes_any:
                out.append(f"parameter {name} removed")
            continue
        j, (_, nkind, nreq, ndefault) = np[name]
        if kind == "positional" and nkind == "positional" and j != i:
            out.append(f"parameter {name} moved")
        if kind != nkind and "var" not in (kind, nkind):
            out.append(f"parameter {name} became {nkind}-only" if nkind == "keyword" else f"parameter {name} kind changed")
        if nreq and not req:
            out.append(f"parameter {name} lost its default")
        elif not req and not nreq and default != ndefault:
            out.append(f"default of {name} changed: {default} -> {ndefault}")
    olds = {p[0] for p in old["params"]}
    out += [f"new required parameter {p[0]}" for p in new["params"] if p[0] not in olds and p[2] and not p[0].startswith("*")]
    return out


def contract_breaks(graph, files_before_after):
    """Names other modules use (from graph, taken before the run) whose contract the run broke.
    files_before_after: {path: (before bytes or None, after bytes or None)}. Returns [{file, name, change, users}]."""
    mod_of = {f: i["module"] for f, i in graph["files"].items()}
    users = defaultdict(lambda: defaultdict(list))
    for user, line, target, name in _named_receipts(graph):
        if target in files_before_after and mod_of.get(user) != mod_of.get(target):
            users[target][name].append(f"{user}:{line}")
    out = []
    for f in sorted(users):
        before, after = files_before_after[f]
        old, new = signatures(before), signatures(after)
        if not old or new is None:  # unreadable before, or does not parse now (the done check reports that)
            continue
        for n in sorted(users[f]):
            if n in old:
                for change in breaks(old[n], new.get(n)):
                    out.append({"file": f, "name": n, "change": change, "users": sorted(set(users[f][n]))})
    return out


_TREES = {}  # (full path, size, mtime) -> ast; the user files of one run, parsed once


def attr_uses(root, receipt):
    """For an import of a whole module (`from pkg import mod`, `import pkg.mod as m`), the names the importing file
    takes from it through attributes (`mod.f(...)`): [(name, line)]. [] for a from-import of a name."""
    if receipt["name"]:
        return []
    stem = os.path.splitext(os.path.basename(receipt["target_file"]))[0]
    if stem == "__init__":
        stem = os.path.basename(os.path.dirname(receipt["target_file"]))
    aliases = set()
    try:
        stmt = ast.parse(receipt["code"].strip().rstrip("(\\").strip()).body[0]
        for a in stmt.names:
            if isinstance(stmt, ast.ImportFrom) and a.name == stem:
                aliases.add(a.asname or a.name)
            elif isinstance(stmt, ast.Import) and a.name.split(".")[-1] == stem:
                aliases.add(a.asname or a.name)
    except (SyntaxError, IndexError, AttributeError):
        aliases.add(stem)
    full = os.path.join(root, receipt["file"])
    try:
        st = os.stat(full)
        key = (full, st.st_size, st.st_mtime_ns)
        if key not in _TREES:
            _TREES[key] = ast.parse(analyze.read_text(full))
        tree = _TREES[key]
    except (OSError, SyntaxError, ValueError):
        return []
    return sorted({(n.attr, n.lineno) for n in ast.walk(tree)
                   if isinstance(n, ast.Attribute) and isinstance(n.value, (ast.Name, ast.Attribute)) and ast.unparse(n.value) in aliases})


def _named_receipts(graph):
    """Every receipt as (user file, line, target file, name): direct from-imports, plus attribute uses of modules."""
    for e in graph["edges"]:
        for r in e["receipts"]:
            if r["name"]:
                yield r["file"], r["line"], r["target_file"], r["name"]
            else:
                for n, line in attr_uses(graph["root"], r):
                    yield r["file"], line, r["target_file"], n
