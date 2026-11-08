"""Functional roles: groups of files above the directory level (observer, segmenter, inference ...).

Roles rarely match folders, and automatic grouping is wrong often enough that a user must confirm it, so this
module only proposes. Every method here is deterministic (same input, same output) and uses the import graph that
analyze.py already builds, file names and folders; a model may later name the groups (see purpose.py), but never
decides them. bench/roles_eval.py scores the methods against a reference built from a project's own docs.

Each method returns {file: group}. Files that many others import (settings, utils) go to the group "shared".
"""
import math, os, re
from collections import Counter, defaultdict

SHARED = "shared"
STOP = {"py", "init", "main", "app", "base", "utils", "util", "common", "core", "lib", "src", "tests", "test", "misc",
        "helpers", "helper", "module", "modules", "models", "types", "io", "api", "v1", "v2", "v3", "new", "old"}


def code_files(graph):
    """The .py files that can belong to a role: not tests, not empty __init__.py files."""
    return sorted(p for p, f in graph["files"].items()
                  if not _is_test(p) and not (p.endswith("__init__.py") and f["lines"] < 3))


def _is_test(p):
    parts = p.split("/")
    return any(x in ("tests", "test") for x in parts[:-1]) or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def intra_module_edges(graph, files):
    """analyze.py drops imports within one module from its edges; the file graph needs them, so re-resolve here."""
    from . import analyze
    keep, w, allfiles = set(files), Counter(), set(graph["files"])
    root = graph["root"]
    for p in files:
        r = analyze._parse(os.path.join(root, p), p)
        for t, _line, _name, _code in analyze._resolved(p, r["imports"], allfiles):
            if t in keep and t != p:
                w[(p, t) if p < t else (t, p)] += 1
    return w


def hubs(graph, files, share=0.05, floor=8):
    """Files imported by many distinct files: max(floor, share of all files). They glue roles together and pull
    clustering around (Bunch's 'omnipresent modules'), so they get their own group."""
    importers = defaultdict(set)
    from . import analyze
    allfiles = set(graph["files"])
    for p in files:
        r = analyze._parse(os.path.join(graph["root"], p), p)
        for t, *_ in analyze._resolved(p, r["imports"], allfiles):
            if t != p:
                importers[t].add(p)
    cut = max(floor, math.ceil(share * len(files)))
    return {f for f in files if len(importers.get(f, ())) >= cut}


def source_root(files):
    """The folder most code lives under (backend/, src/pkg ...): descend while one folder holds over half the files."""
    root = ""
    while True:
        heads = Counter(f[len(root):].split("/")[0] for f in files if f.startswith(root) and "/" in f[len(root):])
        if not heads:
            return root
        top, n = heads.most_common(1)[0]
        if n * 2 <= sum(1 for f in files if f.startswith(root)):
            return root
        root += top + "/"


def by_folder(graph, files=None, depth=1):
    """Baseline: the first `depth` folders below the source root; a file directly in the root is its own group."""
    files = files or code_files(graph)
    root = source_root(files)
    out = {}
    for f in files:
        rest = f[len(root):] if f.startswith(root) else f
        parts = rest.split("/")
        out[f] = "/".join(parts[:min(depth, len(parts) - 1)]) or os.path.splitext(parts[-1])[0]
    return out


def by_module(graph, files=None):
    """Baseline: modfence's own modules (a folder, or a file in a flat folder)."""
    files = files or code_files(graph)
    return {f: graph["files"][f]["module"] for f in files}


def tokens(path):
    """Words in a path: folders and file name split on _ - . and camelCase, lowercased, crudely stemmed, so
    segmenter, segmentation and segment_runner all give 'segment'."""
    raw = re.split(r"[/_.\-]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", path))
    out = []
    for t in raw:
        t = t.lower()
        for suf in ("ations", "ation", "ers", "er", "ing", "ions", "ion", "ors", "or", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                t = t[: -len(suf)]
                break
        if len(t) >= 3 and t not in STOP and not t.isdigit():
            out.append(t)
    return out


def salient(files, min_df=3, max_share=0.25):
    """{file: its most specific shared word}: the path word with the highest IDF among words that at least min_df
    files share and at most max_share of files contain. Files with no such word are absent."""
    df = Counter(t for f in files for t in set(tokens(f)))
    n = len(files)
    out = {}
    for f in files:
        cands = [t for t in set(tokens(f)) if min_df <= df[t] <= max_share * n]
        if cands:
            out[f] = max(cands, key=lambda t: (math.log(n / df[t]), t))
    return out


def by_words(graph, files=None):
    """Lexical: group files by their most specific shared path word, else by folder."""
    files = files or code_files(graph)
    s, fold = salient(files), by_folder(graph, files)
    return {f: s.get(f, fold[f]) for f in files}


def louvain(nodes, weights, resolution=1.0, init=None):
    """Communities of an undirected weighted graph by Louvain modularity optimisation (Blondel et al. 2008), in a
    fixed node order so the result is deterministic. weights: {(a, b): w}. init: {node: label} to start from (a warm
    start; nodes may still move). Returns {node: community id}."""
    part = {n: n for n in nodes}  # node -> community at the current level, as an original-node label
    level_nodes, level_w = list(nodes), dict(weights)
    members = {n: [n] for n in nodes}  # level node -> original nodes
    while True:
        adj = defaultdict(dict)
        for (a, b), w in level_w.items():
            adj[a][b] = adj[a].get(b, 0) + w
            adj[b][a] = adj[b].get(a, 0) + w
        k = {n: sum(adj[n].values()) for n in level_nodes}
        m2 = sum(k.values()) or 1.0
        comm = {n: (init or {}).get(n, n) for n in level_nodes}
        tot = Counter()
        for n in level_nodes:
            tot[comm[n]] += k[n]
        moved_any, improved = bool(init), True
        init = None  # only the first level starts warm
        while improved:
            improved = False
            for n in level_nodes:
                c0 = comm[n]
                links = defaultdict(float)
                for nb, w in adj[n].items():
                    if nb != n:
                        links[comm[nb]] += w
                tot[c0] -= k[n]
                best, gain = c0, links.get(c0, 0) - resolution * tot[c0] * k[n] / m2
                for c in sorted(links):
                    g = links[c] - resolution * tot[c] * k[n] / m2
                    if g > gain + 1e-12:
                        best, gain = c, g
                tot[best] += k[n]
                if best != c0:
                    comm[n] = best
                    improved = moved_any = True
        if not moved_any:
            break
        new_members, new_w = defaultdict(list), Counter()
        for n in level_nodes:
            new_members[comm[n]] += members[n]
        for (a, b), w in level_w.items():  # links inside a community become a self-loop: its degree must not shrink
            ca, cb = comm[a], comm[b]
            new_w[(ca, cb) if ca < cb else (cb, ca)] += w
        members, level_nodes, level_w = dict(new_members), sorted(new_members), dict(new_w)
    return {o: min(group) for group in members.values() for o in group}


def _label(groups, fallback):
    """Name each community by its most common folder (stable, readable); keep names unique."""
    by = defaultdict(list)
    for f, c in groups.items():
        by[c].append(f)
    out, used = {}, Counter()
    for c in sorted(by, key=lambda c: (-len(by[c]), c)):
        name = Counter(fallback[f] for f in by[c]).most_common(1)[0][0]
        used[name] += 1
        name = name if used[name] == 1 else f"{name}~{used[name]}"
        for f in by[c]:
            out[f] = name
    return out


def by_imports(graph, files=None, resolution=1.0):
    """Structural: Louvain communities of the file import graph, hubs set aside as shared. Files with no import
    to or from other code files keep their folder group."""
    files = files or code_files(graph)
    hub = hubs(graph, files)
    rest = [f for f in files if f not in hub]
    w = {e: v for e, v in intra_module_edges(graph, rest).items()}
    linked = {x for e in w for x in e}
    comm = louvain(sorted(linked), w, resolution)
    fold = by_folder(graph, files)
    out = _label(comm, fold)
    out.update({f: fold[f] for f in rest if f not in linked})
    out.update({f: SHARED for f in hub})
    return out


def by_hybrid(graph, files=None, w_import=1.0, w_folder=0.5, w_word=1.0, resolution=1.0, anchored=False):
    """Imports, folders and path words in one weighted graph, then Louvain: two files are pulled together by each
    import line between them (log-scaled), by sharing a folder, and by sharing their most specific path word.
    Hubs are set aside as shared. The weights are the knobs bench/roles_eval.py sweeps."""
    files = files or code_files(graph)
    hub = hubs(graph, files)
    rest = [f for f in files if f not in hub]
    w = Counter()
    for e, v in intra_module_edges(graph, rest).items():
        w[e] += w_import * (1 + math.log(v))
    for key, weight in ((lambda f: os.path.dirname(f), w_folder), (salient(rest).get, w_word)):
        if not weight:
            continue
        group = defaultdict(list)
        for f in rest:
            k = key(f)
            if k is not None:
                group[k].append(f)
        for fs in group.values():
            if len(fs) < 2:
                continue
            per = weight / (len(fs) - 1)  # a folder of 40 files should not outweigh one import line per pair
            for i, a in enumerate(fs):
                for b in fs[i + 1:]:
                    w[(a, b) if a < b else (b, a)] += per
    linked = {x for e in w for x in e}
    fold = by_folder(graph, files)
    init = {f: fold[f] for f in linked} if anchored else None  # start from folders: steadier under small edits
    out = _label(louvain(sorted(linked), dict(w), resolution, init), fold)
    out.update({f: fold[f] for f in rest if f not in linked})
    out.update({f: SHARED for f in hub})
    return out


METHODS = {"module": by_module, "folder": by_folder, "words": by_words, "imports": by_imports, "hybrid": by_hybrid}


# ---------- naming: a model names the groups; code decides what it may change ----------
NAME_SYSTEM = (
    "You map the files of a software system onto its functional roles, for a developer who wants to understand it role "
    "by role. You get groups of files that a deterministic analysis put together, with docstrings, the imports between "
    "groups, and the project's own vocabulary from its docs. First decide the system's roles: between 6 and 15, each a "
    "short lowercase name in the project's own words (e.g. observer, segmenter, inference, memory, api), with one plain "
    "sentence of at most 20 words on what it does for the system. Then assign every group to exactly one role; groups "
    "that do the same job in different places (an old and a new implementation, a platform variant) get the same role. "
    "You may propose moving a single file to another group only when its imports show it works mainly with that group; "
    "quote the evidence. Reply with JSON only: {\"roles\": {\"<role>\": \"<purpose>\"}, \"assign\": {\"<group id>\": "
    "\"<role>\"}, \"moves\": [{\"file\": \"...\", \"to\": \"<group id>\", \"evidence\": \"...\"}]}")
MAX_MOVES = 20


def doc_words(root, limit=80):
    """The project's own vocabulary: headings, bold terms and diagram labels from its top-level docs."""
    lines = []
    for d in ("", "docs", "backend", "src"):
        folder = os.path.join(root, d)
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if n.lower().endswith(".md"):
                try:
                    text = open(os.path.join(folder, n), encoding="utf-8", errors="replace").read(60_000)
                except OSError:
                    continue
                lines += [l.strip() for l in text.splitlines() if l.lstrip().startswith("#") or re.search(r"\[\"?[A-Z][^\]]{2,40}\]|\*\*[^*]{3,30}\*\*", l)]
    seen, out = set(), []
    for l in lines:
        if l not in seen:
            seen.add(l)
            out.append(l[:120])
    return out[:limit]


def name_prompt(graph, groups):
    files = defaultdict(list)
    for f, g in groups.items():
        files[g].append(f)
    cross = Counter()
    for (a, b), v in intra_module_edges(graph, list(groups)).items():
        if groups[a] != groups[b]:
            cross[(groups[a], groups[b])] += v
    parts = ["PROJECT VOCABULARY (from its docs):"] + doc_words(graph["root"]) + [""]
    for g in sorted(files, key=lambda g: (-len(files[g]), g)):
        fs = sorted(files[g])
        parts.append(f"GROUP {g} ({len(fs)} files)")
        for f in fs[:25]:
            doc = graph["files"][f]["doc"]
            parts.append(f"  {f}" + (f"  -- {doc[:100]}" if doc else ""))
        if len(fs) > 25:
            parts.append(f"  ... and {len(fs) - 25} more")
        links = sorted(((v, h) for (s, h), v in cross.items() if s == g), reverse=True)[:5]
        if links:
            parts.append("  imports most from: " + ", ".join(f"{h} ({v})" for v, h in links))
        parts.append("")
    return "\n".join(parts)


def apply_names(graph, groups, answer):
    """The model's names and the moves code can verify: a file moves only if it has more import lines with the target
    group than with its own. Returns ({file: role name}, {role name: purpose}, [accepted moves], [rejected moves])."""
    groups = dict(groups)
    links = defaultdict(Counter)
    for (a, b), v in intra_module_edges(graph, list(groups)).items():
        links[a][b] += v
        links[b][a] += v
    ids = set(groups.values())
    ok, bad = [], []
    for m in (answer.get("moves") or [])[:MAX_MOVES]:
        f, to = m.get("file"), m.get("to")
        if f not in groups or to not in ids or to == groups[f] or groups[f] == SHARED:
            bad.append(dict(m, why="unknown file or group"))
            continue
        with_to = sum(v for o, v in links[f].items() if groups.get(o) == to)
        with_own = sum(v for o, v in links[f].items() if groups.get(o) == groups[f])
        if with_to > with_own:
            ok.append(dict(m, import_lines=[with_own, with_to]))
            groups[f] = to
        else:
            bad.append(dict(m, why=f"imports: {with_own} with its group, {with_to} with {to}"))
    clean = lambda r: re.sub(r"[^a-z0-9 _-]", "", str(r).lower()).strip()
    declared = {clean(r): str(p) for r, p in (answer.get("roles") or {}).items() if clean(r)}
    assign = {g: clean(r) for g, r in (answer.get("assign") or {}).items()}
    # a group keeps its own id unless it is assigned to a declared role: the model cannot invent roles on the fly
    name = {g: assign[g] if assign.get(g) in declared else g for g in ids}
    name[SHARED] = SHARED
    purposes = {r: declared.get(r, "") for r in set(name.values())}
    return {f: name[g] for f, g in groups.items()}, purposes, ok, bad


def propose(graph, claude, method=None):
    """A named role proposal: a deterministic grouping, then one model call to name it and suggest verified moves.
    Returns {"roles": {file: name}, "purposes": {...}, "moves": [...], "rejected": [...], "cost_usd": ...}."""
    from . import purpose
    groups = (method or by_hybrid)(graph)
    answer, cost = purpose._ask(claude, name_prompt(graph, groups), system=NAME_SYSTEM)
    roles_, purposes, ok, bad = apply_names(graph, groups, answer)
    return {"roles": roles_, "purposes": purposes, "moves": ok, "rejected": bad, "cost_usd": cost}


def by_folder_words(graph, files=None, depth=2, flat_at=8):
    """Folders `depth` deep, but a folder with flat_at or more files directly in it (kernel/ with 40 personal_*,
    memory_*, ... files) is split by each file's most specific shared path word."""
    files = files or code_files(graph)
    fold, s = by_folder(graph, files, depth), salient(files)
    flat = Counter(os.path.dirname(f) for f in files)
    return {f: (f"{fold[f]}:{s[f]}" if flat[os.path.dirname(f)] >= flat_at and f in s else fold[f]) for f in files}


def merge_groups(graph, groups, resolution=1.0):
    """Join groups that import each other heavily: Louvain on the graph whose nodes are the groups. A group is
    never split, so folder boundaries the author drew are kept; hubs go to shared."""
    files = list(groups)
    hub = hubs(graph, files)
    w = Counter()
    for (a, b), v in intra_module_edges(graph, [f for f in files if f not in hub]).items():
        ga, gb = groups[a], groups[b]
        w[(ga, gb) if ga <= gb else (gb, ga)] += v
    nodes = sorted(set(groups.values()))
    comm = louvain(nodes, dict(w), resolution)
    size = Counter(groups.values())
    name = {}
    for c in set(comm.values()):  # a merged group is named after its biggest member group
        name[c] = max((g for g in nodes if comm[g] == c), key=lambda g: (size[g], g))
    out = {f: name[comm[g]] for f, g in groups.items()}
    out.update({f: SHARED for f in hub})
    return out


METHODS.update({
    "folder_words": by_folder_words,
    "folder_merge": lambda g, files=None: merge_groups(g, by_folder(g, files, depth=2)),
    "folder_words_merge": lambda g, files=None: merge_groups(g, by_folder_words(g, files)),
})


# ---------- the user's roles: stored, renamed and corrected by hand ----------
# Roles keep a stable id (r1, r2 ...); the name is only a label, so renaming never touches file assignments, fences
# or history. Names are checked: clear but short.
NAME_MAX, NAME_WORDS = 24, 3
DEFAULT = by_folder_words


def store_path(root):
    return os.path.join(root, ".modfence", "roles.json")


def load_store(root):
    import json
    try:
        with open(store_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_store(root, d):
    import json
    from .runner import state_dir, write_text
    state_dir(root)  # creates .modfence/ and git-ignores it
    write_text(store_path(root), json.dumps(d, indent=1, ensure_ascii=False))


def tidy(name):
    """A proposed name made readable: separators to spaces, at most NAME_WORDS words and NAME_MAX characters."""
    words = re.sub(r"[/:_~\\]+", " ", str(name)).split()
    out = ""
    for w in words[:NAME_WORDS]:
        if len(out) + len(w) + (1 if out else 0) > NAME_MAX:
            break
        out = f"{out} {w}" if out else w
    return out or "unnamed"


def check_name(store, rid, name):
    """The cleaned name, or ValueError saying why it cannot be used."""
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("A role needs a name.")
    if len(name) > NAME_MAX or len(name.split()) > NAME_WORDS:
        raise ValueError(f"Keep it short: at most {NAME_WORDS} words and {NAME_MAX} characters.")
    if any(c in name for c in "/\\:") or not name.isprintable():
        raise ValueError("Use letters, digits, spaces, - or _.")
    for other, r in store["roles"].items():
        if other != rid and r["name"].casefold() == name.casefold():
            raise ValueError(f"Another role is already called {r['name']}.")
    return name


def to_store(files_to_name, purposes, how, cost=None):
    names = sorted(set(files_to_name.values()), key=lambda n: (n == SHARED, n))
    roles_, ids = {}, {}
    for i, n in enumerate(names, 1):
        rid = f"r{i}"
        label = tidy(n)
        while any(r["name"].casefold() == label.casefold() for r in roles_.values()):
            label = tidy(f"{label} {i}")
        ids[n] = rid
        roles_[rid] = {"name": label, "purpose": purposes.get(n, "") if n != SHARED else "Code most other parts import: settings, helpers, shared types."}
    return {"status": "proposed", "how": how, "cost_usd": cost, "roles": roles_,
            "files": {f: ids[n] for f, n in sorted(files_to_name.items())}}


def propose_and_store(root, graph, claude):
    """Group deterministically (DEFAULT), then one model call maps the groups onto 6-15 named roles. Without a model
    the folder groups are stored as they are. Measured on one 400-file system: see docs/EVALUATION.md."""
    groups = DEFAULT(graph)
    try:
        if not claude:
            raise RuntimeError("no Claude Code CLI")
        from . import purpose
        answer, cost = purpose._ask(claude, name_prompt(graph, groups), system=NAME_SYSTEM)
        named, purposes, _ok, _bad = apply_names(graph, groups, answer)
        store = to_store(named, purposes, "folders and path words, roles named by a model", cost)
    except (RuntimeError, OSError, ValueError) as e:
        store = to_store(by_folder(graph, depth=2), {}, f"folders only ({e})")
    save_store(root, store)
    return store


def rename(root, rid, name):
    store = load_store(root)
    if not store or rid not in store["roles"]:
        raise LookupError("no such role")
    store["roles"][rid]["name"] = check_name(store, rid, name)
    save_store(root, store)
    return store


def move(root, path, rid):
    store = load_store(root)
    if not store or rid not in store["roles"]:
        raise LookupError("no such role")
    store["files"][path] = rid
    save_store(root, store)
    return store


def add_role(root, name, purpose_=""):
    store = load_store(root)
    if not store:
        raise LookupError("no roles yet")
    rid = f"r{1 + max([int(k[1:]) for k in store['roles']] or [0])}"
    store["roles"][rid] = {"name": check_name(store, rid, name), "purpose": str(purpose_)[:200]}
    save_store(root, store)
    return store


def confirm(root):
    store = load_store(root)
    if not store:
        raise LookupError("no roles yet")
    store["status"] = "confirmed"
    save_store(root, store)
    return store


def view(root, graph):
    """{"status", "how", "cost_usd", "roles": [{id, name, purpose, files}], "unassigned": [code files with no role]}.
    Files deleted since are dropped; files added since are listed as unassigned until the user places them."""
    store = load_store(root)
    if not store:
        return {"status": "none", "roles": [], "unassigned": []}
    code = set(code_files(graph))
    members = defaultdict(list)
    for f, rid in store["files"].items():
        if f in code and rid in store["roles"]:
            members[rid].append(f)
    roles_ = [dict(id=rid, files=sorted(members[rid]), **r) for rid, r in store["roles"].items()]
    roles_.sort(key=lambda r: (r["name"] == SHARED, -len(r["files"]), r["name"]))
    return {"status": store["status"], "how": store.get("how"), "cost_usd": store.get("cost_usd"), "roles": roles_,
            "unassigned": sorted(code - set(store["files"]))}
