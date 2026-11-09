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


def importers(graph, files):
    """{file: the files in `files` that import it}, imports inside one module included."""
    from . import analyze
    out, allfiles = defaultdict(set), set(graph["files"])
    for p in files:
        r = analyze._parse(os.path.join(graph["root"], p), p)
        for t, *_ in analyze._resolved(p, r["imports"], allfiles):
            if t != p:
                out[t].add(p)
    return out


def hubs(graph, files, share=0.05, floor=8):
    """Files imported by many distinct files: max(floor, share of all files). They glue roles together and pull
    clustering around (Bunch's 'omnipresent modules'), so they get their own group."""
    imp = importers(graph, files)
    cut = max(floor, math.ceil(share * len(files)))
    return {f for f in files if len(imp.get(f, ())) >= cut}


# ---------- cross-cutting files: not features, so not boxes and not edited by default (golden rules 2, 4, 6) ----------
# Fan-in alone cannot tell settings.py from memory.py (both used by most roles), so position in the import graph is
# combined with naming conventions most projects follow. ponytail: word lists, extend them when a project disagrees.
ENTRY = re.compile(r"^(__main__|main|\w+_main|main_\w+|manage|wsgi|asgi|run)$")
DOOR = {"route", "routes", "router", "routers", "views", "endpoint", "endpoints", "handlers", "controllers"}
SHARE = re.compile(r"^(settings|config|configs|conf|constants|consts|env|auth|permissions|clients?|middleware|"
                   r"utils?|helpers?|common|logging_?\w*|log)$")


def kinds(graph, role_of):
    """({file: "entry" | "door" | "shared"}, {door file: role id it serves}), from the import graph and file names.
    entry: nothing imports it and its name says main. door: a routes/views/handlers file only entries import; it
    serves the role whose code it imports most. shared: a settings/config/auth/utils-style name used by 2+ roles."""
    code = [f for f in code_files(graph)]
    imp = importers(graph, code)
    stem = lambda f: os.path.splitext(os.path.basename(f))[0].lower()
    kind = {f: "entry" for f in code if not imp.get(f) and ENTRY.match(stem(f))}
    for f in code:
        if f in kind:
            continue
        if SHARE.match(stem(f)) and len({role_of.get(p) for p in imp.get(f, ())} - {role_of.get(f), None}) >= 2:
            kind[f] = "shared"
        elif DOOR & set(re.split(r"[/_.\-]+", f.lower())) and len(imp.get(f, ())) <= 2:  # an app file mounts it
            kind[f] = "door"
    uses = defaultdict(Counter)  # a door serves the role of the file named like it (memory_routes -> memory.py), else
    for t, ps in imp.items():     # the role it imports most
        for p in ps:
            if kind.get(p) == "door" and t not in kind and role_of.get(t):
                core = set(re.split(r"[_.\-]+", stem(p))) - DOOR
                uses[p][role_of[t]] += 100 if core and core <= set(re.split(r"[_.\-]+", stem(t))) else 1
    door_of = {f: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for f, c in uses.items() if c}
    for f in [f for f, k in kind.items() if k == "door" and f not in door_of]:
        kind[f] = "entry"  # a door to nothing modfence knows: list it with the entries
    return kind, door_of


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
    "You name the functional roles of a software system for a developer who will pick a role and ask a coding agent to "
    "change it. Each group of files below is one role, fixed by a deterministic analysis of the code and its change "
    "history; do not move files or merge groups. You get each group's files with docstrings, the imports between groups, "
    "and the project's own vocabulary from its docs. For every group write a short lowercase name of 1 to 3 words in "
    "the project's own words (e.g. observer, segmenter, inference, memory, api), different from the other names, and one "
    "plain sentence of at most 20 words on what it does for the system. Reply with JSON only: "
    "{\"roles\": {\"<group id>\": {\"name\": \"...\", \"purpose\": \"...\"}}}")


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


ROLE_MAX, ROLE_CAP = 15, 0.25


def by_history(graph, files=None, most=ROLE_MAX, cap=ROLE_CAP, changes=None, top_w=0.25):
    """by_folder_words groups merged into at most `most` roles, none over `cap` of the files: groups that changed
    together (git history), import each other and share folders merge first (suggest_areas, one level down).
    Measured with bench/role_bench.py: it kept multi-file commits in one role better than the other methods across
    five histories, and better than model-made roles (docs/EVALUATION.md section 6). Without git, imports and folders."""
    fw = by_folder_words(graph, files)
    changes = change_sets(graph["root"], set(fw)) if changes is None else changes  # a bench passes older commits only
    groups = suggest_areas(fw, role_imports(graph, fw), changes, most, cap, top_w)
    size = Counter(fw.values())
    label = {u: max(g, key=lambda x: (size[x], x)) for g in groups for u in g}
    return {f: label[u] for f, u in fw.items()}


METHODS["history"] = by_history


# ---------- the user's roles: stored, renamed and corrected by hand ----------
# Roles keep a stable id (r1, r2 ...); the name is only a label, so renaming never touches file assignments, fences
# or history. Names are checked: clear but short.
NAME_MAX, NAME_WORDS = 24, 3
DEFAULT = by_folder_words  # the fine groups by_history starts from


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
    """Group with by_history (deterministic), then one small model call names each role. Without a model, or for a
    group it leaves unnamed, the group keeps its folder or path-word label."""
    groups = by_history(graph)
    try:
        if not claude:
            raise RuntimeError("no Claude Code CLI")
        from . import purpose
        answer, cost = purpose._ask(claude, name_prompt(graph, groups), system=NAME_SYSTEM)
        named = {g: v for g, v in (answer.get("roles") or {}).items() if isinstance(v, dict) and str(v.get("name") or "").strip()}
        how = "folders, path words, imports and change history; named by a model"
    except (RuntimeError, OSError, ValueError) as e:
        named, cost, how = {}, None, f"folders, path words, imports and change history ({e})"
    name, purposes = {}, {}
    for g in sorted(set(groups.values())):
        n = re.sub(r"[^a-z0-9 _-]", "", str((named.get(g) or {}).get("name") or g).lower()).strip() or g
        while n in purposes:  # two groups never share a name, or to_store would merge them
            n += "+"
        name[g], purposes[n] = n, str((named.get(g) or {}).get("purpose") or "")[:200]
    store = to_store({f: name[g] for f, g in groups.items()}, purposes, how, cost)
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


# ---------- areas: the first level, at most AREA_MAX boxes of roles ----------
# A model groups the roles (it knows what "capture" or "evaluation" means); the deterministic grouping that measured
# best for vibe coding (bench/area_bench.py, docs/EVALUATION.md) is its evidence and the fallback when it fails.
AREA_MAX = 7
AREA_SYSTEM = (
    "You name the areas of a software system for a developer who will pick one area, then one role in it, and ask a "
    "coding agent to change it. Each area is a fixed group of roles; do not move roles. For each area, in the order "
    "given, write a name of 1 to 3 lowercase words in the project's own vocabulary and one plain sentence of at most 20 "
    "words on what it does. Reply with JSON only: {\"areas\": [{\"name\": \"...\", \"purpose\": \"...\"}]}")


def role_imports(graph, role_of):
    """{frozenset((role a, role b)): import lines between them}, entry points, doors and shared config left out."""
    out = Counter()
    for t, ps in importers(graph, list(role_of)).items():
        for p in ps:
            if t in role_of and role_of[p] != role_of[t]:
                out[frozenset((role_of[p], role_of[t]))] += 1
    return out


AREA_CAP = 0.4  # no area may hold more than this share of the code: a blob fits every change and fences nothing


def change_sets(root, files, limit=2000, big=30):
    """The files each recent git commit changed (newest `limit`), keeping commits of 1 to `big` known files; [] when
    the project has no git history. Read-only."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", root, "log", "--no-merges", f"-{limit}", "--name-only", "--format=%x1e"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    sets = ({l for l in chunk.splitlines() if l in files} for chunk in out.split("")[1:])
    return [c for c in sets if 1 <= len(c) <= big]


def _cos(a, b):
    n = math.sqrt(sum(x * x for x in a.values())) * math.sqrt(sum(x * x for x in b.values()))
    return sum(a[k] * b[k] for k in a) / n if n else 0.0


def agglomerate(names, size, sim, most=AREA_MAX, cap=AREA_CAP, tiny=0.02):
    """Average-linkage merging of `names` into `most` groups. A merge is worth less the bigger its result, and no group
    may pass `cap` of the total size while another merge is possible. A group under `tiny` of the total joins its most
    similar group first, so the boxes left are not one-file crumbs. Pair sums are updated per merge. Deterministic."""
    groups = {i: [u] for i, u in enumerate(sorted(names))}
    n = sum(size[u] for u in names) or 1
    gsize = {i: size[g[0]] for i, g in groups.items()}
    tot = {(i, j): sim(groups[i][0], groups[j][0]) for i in groups for j in groups if i < j}
    while len(groups) > most:
        score = lambda p: tot[p] / (len(groups[p[0]]) * len(groups[p[1]])) * (1 - (gsize[p[0]] + gsize[p[1]]) / n)
        ok = [p for p in tot if gsize[p[0]] + gsize[p[1]] <= cap * n] or list(tot)
        crumb = lambda p: min(gsize[p[0]], gsize[p[1]]) < tiny * n and tot[p] > 0
        i, j = max(ok, key=lambda p: (crumb(p), score(p), -p[0], -p[1]))
        groups[i] += groups.pop(j)
        gsize[i] += gsize.pop(j)
        for x in groups:
            if x != i:
                tot[(min(i, x), max(i, x))] = tot.get((min(i, x), max(i, x)), 0) + tot.get((min(j, x), max(j, x)), 0)
        tot = {p: v for p, v in tot.items() if j not in p}
    return sorted((sorted(g) for g in groups.values()), key=lambda g: (-sum(size[u] for u in g), g))


def suggest_areas(role_of, imports, changes=(), most=AREA_MAX, cap=AREA_CAP, top_w=0.25):
    """[[role, ...], ...], at most `most` areas, none over `cap` of the files: roles that change together (git history),
    import each other (per file pair) and share folders (a hint) are merged first. Of the groupings measured in
    bench/area_bench.py this one fitted the most multi-role commits into one area at a capped area size."""
    size = Counter(role_of.values())
    together, alone = Counter(), Counter()
    for c in changes:
        rs = sorted({role_of[f] for f in c if f in role_of})
        alone.update(rs)
        together.update(frozenset(p) for i, a in enumerate(rs) for p in ((a, b) for b in rs[i + 1:]))
    fold, top = defaultdict(Counter), defaultdict(Counter)
    for f, r in role_of.items():
        fold[r]["/".join(f.split("/")[:2])] += 1
        top[r][f.split("/")[0] if "/" in f else "."] += 1  # the top folder pulls in small groups nothing else links

    def sim(a, b):
        k = frozenset((a, b))
        co = together[k] / math.sqrt(alone[a] * alone[b]) if alone[a] and alone[b] else 0.0
        return co + min(1.0, imports[k] / math.sqrt(size[a] * size[b])) + 0.5 * _cos(fold[a], fold[b]) + top_w * _cos(top[a], top[b])
    return agglomerate(list(size), size, sim, most, cap)


def area_prompt(store, role_of, groups):
    """The areas to name: each with its roles, their purposes, sizes and main folders."""
    size = Counter(role_of.values())
    lines = []
    for i, g in enumerate(groups, 1):
        lines.append(f"AREA {i}")
        for rid in g:
            folders = Counter(os.path.dirname(f) or "." for f, r in role_of.items() if r == rid).most_common(2)
            lines.append(f"- {store['roles'][rid]['name']} ({size[rid]} files; {', '.join(f'{d}/' for d, _ in folders)}): "
                         f"{store['roles'][rid].get('purpose', '')}")
    return "\n".join(lines)


def propose_areas(root, graph, claude, model="haiku"):
    """Group the stored roles into at most AREA_MAX areas with suggest_areas (deterministic; a model grouping measured
    no better, docs/EVALUATION.md section 6), then one small model call names them. Without a model, or if its answer
    does not fit, an area is named after its biggest roles. Stored in the roles store."""
    store = load_store(root)
    if not store:
        raise LookupError("no roles yet")
    v = view(root, graph)
    role_of = {f: r["id"] for r in v["roles"] for f in r["files"] if f not in v["kinds"]}
    groups = suggest_areas(role_of, role_imports(graph, role_of), change_sets(root, set(role_of)))
    rest = sorted({r["id"] for r in v["roles"]} - set(role_of.values()))  # roles left with no own files
    groups += [rest] if rest else []
    names, cost, how = [], None, "grouped by imports, change history and folders"
    try:
        if not claude:
            raise RuntimeError("no Claude Code CLI")
        from . import purpose
        answer, cost = purpose._ask(claude, area_prompt(store, role_of, groups), system=AREA_SYSTEM, model=model)
        names = [(tidy(str(a.get("name") or "")), str(a.get("purpose") or "")[:200]) for a in answer.get("areas") or []]
        if len(names) != len(groups) or not all(n for n, _ in names):
            raise ValueError("the names do not match the areas")
        how += f"; named by a model ({model})"
    except (RuntimeError, OSError, ValueError) as e:
        names, how = [], how + f"; named after their biggest roles ({e})"
    areas = {}
    for i, g in enumerate(groups, 1):
        name, purpose_ = names[i - 1] if names else (tidy(" ".join(store["roles"][r]["name"] for r in g[:2])), "")
        while any(a["name"].casefold() == name.casefold() for a in areas.values()):
            name = tidy(f"{name} {i}")
        areas[f"a{i}"] = {"name": name, "purpose": purpose_, "roles": g}
    store["areas"], store["areas_how"], store["areas_cost_usd"] = areas, how, cost
    save_store(root, store)
    return store


def rename_area(root, aid, name):
    store = load_store(root)
    if not store or aid not in (store.get("areas") or {}):
        raise LookupError("no such area")
    store["areas"][aid]["name"] = tidy(str(name or "")) or store["areas"][aid]["name"]
    save_store(root, store)
    return store


def move_role(root, rid, aid):
    """Put a role in another area (an area left empty disappears)."""
    store = load_store(root)
    areas = (store or {}).get("areas") or {}
    if aid not in areas or not store or rid not in store["roles"]:
        raise LookupError("no such area or role")
    for a in areas.values():
        a["roles"] = [r for r in a["roles"] if r != rid]
    areas[aid]["roles"].append(rid)
    store["areas"] = {k: a for k, a in areas.items() if a["roles"]}
    save_store(root, store)
    return store


PART_MAX = 8  # ponytail: about what a person holds in mind at once (Miller); one number, not a setting


def role_parts(files, most=PART_MAX):
    """Level 2: a role's files as at most `most` parts. A role of `most` files or fewer shows its files. A bigger one
    groups files by the word their names share most widely (all *_round files, both *_judge files), else by folder;
    while there are too many parts the smallest word group falls back to its folders, and only then do the smallest
    groups go to "other". Returns {file: part label}, a word as written in the file names or a folder ending in /."""
    if len(files) <= most:
        return {f: os.path.basename(f) for f in files}
    folder = lambda f: (os.path.dirname(f) or ".") + "/"
    shown = defaultdict(Counter)  # stem -> the words it came from, to label parts as people wrote them
    for f in files:
        for raw in re.split(r"[_.\-]+", os.path.basename(f)):
            for t in tokens(raw):
                shown[t][raw.lower()] += 1
    # a word that is also a folder here would read like that folder ("evaluation" next to "evaluation/"): not a name
    in_folders = {t for f in files for t in tokens(os.path.dirname(f))}
    names = {f: set(tokens(os.path.basename(f))) - in_folders for f in files}
    df = Counter(t for ts in names.values() for t in ts)
    key = {}
    for f in files:
        words = [t for t in names[f] if 2 <= df[t] <= len(files) / 2]
        key[f] = shown[max(words, key=lambda t: (df[t], t))].most_common(1)[0][0] if words else folder(f)
    size = Counter(key.values())
    key = {f: k if size[k] > 1 else folder(f) for f, k in key.items()}  # no part of one file named by a word
    while True:
        size = Counter(key.values())
        words = [k for k in size if not k.endswith("/")]
        if len(size) <= most or not words:
            break
        small = min(words, key=lambda k: (size[k], k))
        key = {f: folder(f) if k == small else k for f, k in key.items()}
    keep = set(size) if len(size) <= most else {k for k, _ in sorted(size.items(), key=lambda kv: (-kv[1], kv[0]))[:most - 1]}
    return {f: k if k in keep else "other" for f, k in key.items()}


def view(root, graph):
    """{"status", "how", "cost_usd", "roles": [{id, name, purpose, files, parts}], "unassigned": [code files with no role]}.
    Files deleted since are dropped; files added since are listed as unassigned until the user places them."""
    store = load_store(root)
    if not store:
        return {"status": "none", "roles": [], "unassigned": []}
    code = set(code_files(graph))
    members = defaultdict(list)
    for f, rid in store["files"].items():
        if f in code and rid in store["roles"]:
            members[rid].append(f)
    roles_ = [dict(id=rid, files=sorted(members[rid]), parts=role_parts(sorted(members[rid])), **r) for rid, r in store["roles"].items()]
    roles_.sort(key=lambda r: (r["name"] == SHARED, -len(r["files"]), r["name"]))
    kind, door_of = kinds(graph, {f: rid for rid, fs in members.items() for f in fs})
    areas = [dict(id=aid, **a) for aid, a in (store.get("areas") or {}).items()]
    placed = {r for a in areas for r in a["roles"]}
    if areas and any(r["id"] not in placed for r in roles_):  # roles added since the areas were made
        areas.append({"id": "?", "name": "not placed yet", "purpose": "Roles added since the areas were made.",
                      "roles": [r["id"] for r in roles_ if r["id"] not in placed]})
    return {"status": store["status"], "how": store.get("how"), "cost_usd": store.get("cost_usd"), "roles": roles_,
            "unassigned": sorted(code - set(store["files"])), "kinds": kind, "doors": door_of,
            "areas": areas, "areas_how": store.get("areas_how"), "areas_cost_usd": store.get("areas_cost_usd")}
