"""MODULES.md: the project's first-level modules, one file that people, agents, the fence, the receipt and CI all read
(golden rule 1).

    # Modules

    ## observer
    Watches the screen and the input.
    - backend/kernel/observers/
    - windows_app/personal/selfcheck.py

One `## name` per module (at most 7), a line of purpose, then one `- path` line per folder (ending in /), file, or
glob (`*` also crosses folders). A file belongs to the module with the longest matching line, so a folder can go to
one module and a file inside it to another; a file no line matches is unassigned, and test files belong to no module
(everyone runs and extends them). modfence writes this file only when the user saves the map's modules (`save`), and writes it back when
the map renames a module or moves a role; edits by hand are read as they are.
"""
import fnmatch, os, re

FILE = "MODULES.md"
HEADER = ("# Modules\n\nThe first-level modules of this project, written by modfence and edited by hand when needed.\n"
          "Agents: work inside one module; a change in another module needs the user's approval.\n")


def parse(text):
    """[{"name", "purpose", "paths"}] from the text of a MODULES.md."""
    mods, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = {"name": line[3:].strip(), "purpose": "", "paths": []}
            mods.append(cur)
        elif cur is not None and re.match(r"^\s*[-*] ", line):
            cur["paths"].append(line.strip()[2:].strip().strip("`"))
        elif cur is not None and line.strip() and not cur["paths"] and not line.startswith("#"):
            cur["purpose"] = (cur["purpose"] + " " + line.strip()).strip()
    return mods


def load(root):
    try:
        with open(os.path.join(root, FILE), encoding="utf-8") as f:
            return parse(f.read())
    except OSError:
        return None


def render(mods):
    out = [HEADER]
    for m in mods:
        out.append(f"## {m['name']}")
        if m.get("purpose"):
            out.append(m["purpose"])
        out += [f"- {p}" for p in m["paths"]]
        out.append("")
    return "\n".join(out)


def save(root, mods):
    with open(os.path.join(root, FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write(render(mods))


def match(pattern, path):
    pattern = pattern.replace("\\", "/").lstrip("./") if pattern not in (".", "./") else ""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def _is_test(path):
    parts = path.split("/")
    return any(p in ("tests", "test") for p in parts[:-1]) or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def owner(mods, path):
    """The module whose longest line matches path; None for a test file or a file no line matches."""
    if _is_test(path):
        return None
    best = max(((len(p), m["name"]) for m in mods or [] for p in m["paths"] if match(p, path)), default=None)
    return best and best[1]


MAJORITY = 0.6  # ponytail: a folder goes to a module holding 60% of its files; the rest are listed one by one


def compress(owner_of):
    """{module: lines}: the fewest folder and file lines that give every file the owner owner_of says, with the longest
    line winning. A folder goes to the module that holds most of its files (files nobody owns ride along); a file or
    folder inside it held by another module gets its own, longer, line."""
    tree = {}
    for f in owner_of:
        parts = f.split("/")
        for i in range(len(parts)):
            tree.setdefault("/".join(parts[:i]), set()).add("/".join(parts[:i + 1]))
    lines = {}

    def walk(d, claimed):
        held = [owner_of[f] for f in owner_of if owner_of[f] and (not d or f.startswith(d + "/"))]
        if not held:
            return
        top = max(set(held), key=held.count)
        if d and top != claimed and held.count(top) >= MAJORITY * len(held):
            lines.setdefault(top, []).append(d + "/")
            claimed = top
        for child in sorted(tree.get(d, ())):
            if child in tree:
                walk(child, claimed)
            elif owner_of.get(child) and owner_of[child] != claimed:
                lines.setdefault(owner_of[child], []).append(child)
    walk("", None)
    return lines


def from_store(store, code):
    """Modules from the map's areas (roles.json): names and purposes as the user left them, paths compressed."""
    role_area = {r: aid for aid, a in (store.get("areas") or {}).items() for r in a.get("roles", [])}
    lines = compress({f: role_area.get(store["files"].get(f)) for f in code if not _is_test(f)})
    return [{"name": a["name"], "purpose": a.get("purpose", ""), "paths": lines[aid]}
            for aid, a in (store.get("areas") or {}).items() if aid in lines]


def sync_store(store, mods, code):
    """The map's areas as MODULES.md says: one area per module, in its order, holding the roles most of whose files it
    owns. Returns True when the areas changed. Roles no module owns are left out (the map lists them apart)."""
    votes = {}
    for f in code:
        rid, m = store["files"].get(f), owner(mods, f)
        if rid and m:
            votes.setdefault(rid, {}).setdefault(m, 0)
            votes[rid][m] += 1
    best = {rid: max(v, key=v.get) for rid, v in votes.items()}
    areas = {f"m{i + 1}": {"name": m["name"], "purpose": m["purpose"], "roles": sorted(r for r, b in best.items() if b == m["name"])}
             for i, m in enumerate(mods)}
    changed = areas != store.get("areas")
    store["areas"] = areas
    return changed
