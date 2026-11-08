"""The AI-only brief of a fence (golden rules 1, 4 and 6).

During a sealed run the agent cannot read code outside its fence. This brief is all it sees of the rest of the project.
It is built from the import graph's receipts and Python's ast, with no model call, and holds three things:

- deps: for each module the fence imports from, only the names it uses, as one-line stubs (Agentless-style skeletons);
- contract: the fence's names that other modules use, with who uses them (the fence must keep these working);
- near: one line per neighbouring module (one hop, after RepoGraph: two hops measured worse).

It is written for the model, not for people. ENCODINGS gives three renderings of the same facts; which one ships is
decided by measurement (tokens x task success), see bench/brief_probe.py.
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
        ms = " ".join(f"{m['name'].split('.')[-1]}({m['args']})" for m in methods if not m["name"].split(".")[-1].startswith("_"))
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
    root, mine = graph["root"], scope_files(graph, scope)
    mod_of = {f: i["module"] for f, i in graph["files"].items()}
    docs = {m["id"]: m["doc"] for m in graph["modules"]}
    used = defaultdict(lambda: defaultdict(int))   # (module, target file) -> name -> import lines in the fence
    users = defaultdict(lambda: defaultdict(list))  # fence file -> name -> [user file:line]
    for e in graph["edges"]:
        for r in e["receipts"]:
            a, b = r["file"] in mine, r["target_file"] in mine
            if a and not b:
                used[(mod_of[r["target_file"]], r["target_file"])][r["name"]] += 1  # None: the whole module
            elif b and not a:
                users[r["target_file"]][r["name"] or "(module)"].append(f"{r['file']}:{r['line']}")
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
    out = ["## Outside the fence (you cannot read these files; this is what they offer you)"] + _grouped(full, rest, lambda m: m + ":")
    if f["contract"]:
        out.append("## The fence's contract (other modules use these; keep their names and parameters working)")
        cfull, crest = _fit(f["contract"], lambda c: f"{_terse(c['stub'])}  <- {', '.join(c['mods'])}", budget // 4)
        out += [l for _, l in cfull] + (["also used: " + ", ".join(c["name"] for c in crest)] if crest else [])
    left = [m for m in f["near"] if not any(d["mod"] == m for d in f["deps"])]
    if left:
        out.append("## Also connected: " + ", ".join(left))
    if f["others"] > 0:
        out.append(f"({f['others']} more modules, not connected to the fence)")
    return "\n".join(out)


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
    out = [f"{m}: " + ", ".join(sorted(ns)) for m, ns in sorted(by.items())]
    if f["contract"]:
        out.append("keep: " + ", ".join(c["name"] for c in f["contract"]))
    return "\n".join(out)[:budget]


ENCODINGS = {"sig": render_sig, "ids": render_ids, "iface": render_iface}


def brief(graph, scope, encoding="sig", budget=BUDGET):
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
