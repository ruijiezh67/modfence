"""Which way of building the first level of the map is best for module vibe coding? (golden rules 2, 4 and 7)

Vibe coding with modfence is: pick one box, let the agent change it. So a first level is good when a real change fits
in one box (the fence covers it) and that box is small (the fence is tight: few tokens, little else exposed). Both are
measured on the project's own git history, which is free and not made up:

  one_box   share of held-out commits whose changed files all lie in one box
  cover     mean share of the project's code files inside the boxes a commit touches (lower = tighter fence)
  net       one_box - cover: changes that fit one box, minus the code opened to fence them (higher is better)
  largest   share of code files in the biggest box (a blob that holds everything scores one_box 1 and cover ~1)

Units are the project's roles: the stored ones (.modfence/roles.json) when present, else roles.DEFAULT's groups
(folders and path words, no model). Entry points, doors and shared config (roles.kinds) are left out, as on the map.
Every method returns at most MAX boxes. Commits: the newest TEST share is held out; the co-change methods learn only
from the older commits. A commit counts when it changes 1 to 30 unit files that still exist (bigger ones are
refactors or reformatting, not one change). Only held-out commits that touch 2 or more units are scored: a change
inside one unit fits one box under any grouping, so it cannot tell groupings apart (in a first run that kept them,
random partitions scored as well as most methods). Random partitions with the same box count are the floor.

Usage: python bench/area_bench.py REPO [REPO ...] [--json OUT]
"""
import argparse, collections, itertools, json, math, os, random, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence import analyze, roles  # noqa: E402

MAX, TEST, BIG = 7, 0.3, 30


def units_of(root, graph):
    v = roles.view(root, graph)
    if v["roles"]:
        unit = {f: r["name"] for r in v["roles"] for f in r["files"]}
        kinds = v.get("kinds") or {}
        how = "stored roles"
    else:
        unit = {f: g for f, g in roles.DEFAULT(graph).items()}
        kinds, _ = roles.kinds(graph, unit)
        how = "roles.DEFAULT groups"
    return {f: u for f, u in unit.items() if f not in kinds}, how


def commits(root, files):
    out = subprocess.run(["git", "-C", root, "log", "--no-merges", "--name-only", "--format=%x1e"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout
    cs = [[l for l in c.splitlines() if l in files] for c in out.split("")[1:]]
    cs = [c for c in cs if 1 <= len(c) <= BIG][::-1]  # oldest first
    cut = int(len(cs) * (1 - TEST))
    return cs[:cut], cs[cut:]


# ---------- similarity between units ----------
def import_sim(graph, unit):
    imp, size = collections.Counter(), collections.Counter(unit.values())
    for t, ps in roles.importers(graph, list(unit)).items():
        for p in ps:
            if t in unit and unit[p] != unit[t]:
                imp[frozenset((unit[p], unit[t]))] += 1
    return lambda a, b: min(1.0, imp[frozenset((a, b))] / math.sqrt(size[a] * size[b]))


def cos(a, b):
    n = math.sqrt(sum(x * x for x in a.values())) * math.sqrt(sum(x * x for x in b.values()))
    return sum(a[k] * b[k] for k in a) / n if n else 0.0


def vec_sim(unit, key):
    vec = collections.defaultdict(collections.Counter)
    for f, u in unit.items():
        for k in key(f):
            vec[u][k] += 1
    return lambda a, b: cos(vec[a], vec[b])


def cochange_sim(unit, train):
    together, alone = collections.Counter(), collections.Counter()
    for c in train:
        us = sorted({unit[f] for f in c})
        for u in us:
            alone[u] += 1
        for a, b in itertools.combinations(us, 2):
            together[frozenset((a, b))] += 1
    return lambda a, b: together[frozenset((a, b))] / math.sqrt(alone[a] * alone[b]) if alone[a] and alone[b] else 0.0


CAP = 0.4  # no box may hold more than this share of the code: a blob fits every change and fences nothing


def agglo(units, size, sim, k=MAX, balance=True, cap=None):
    """Average-linkage merging until k boxes; with balance, a merge is worth less the bigger the result (no blob).
    Pair sums are kept and updated on each merge, so this is O(n^2) per merge."""
    groups = {i: [u] for i, u in enumerate(sorted(units))}
    n = sum(size.values())
    gsize = {i: size[g[0]] for i, g in groups.items()}
    tot = {(i, j): sim(groups[i][0], groups[j][0]) for i in groups for j in groups if i < j}
    while len(groups) > k:
        def score(p):
            i, j = p
            v = tot[p] / (len(groups[i]) * len(groups[j]))
            return v * (1 - (gsize[i] + gsize[j]) / n) if balance else v
        ok = [p for p in tot if cap is None or gsize[p[0]] + gsize[p[1]] <= cap * n] or list(tot)
        i, j = max(ok, key=lambda p: (score(p), -p[0], -p[1]))
        groups[i] += groups.pop(j)
        gsize[i] += gsize.pop(j)
        for x in groups:
            if x != i:
                a, b = (i, x) if i < x else (x, i)
                tot[(a, b)] = tot.get((a, b), 0) + tot.get((min(j, x), max(j, x)), 0)
        tot = {p: v for p, v in tot.items() if j not in p}
    return list(groups.values())


# ---------- the methods: each returns {unit: box} ----------
def m_folder(unit, size, **_):
    """The unit's main top folder below the source root; beyond MAX folders the smallest share one 'other' box."""
    base = roles.source_root(list(unit))
    top = lambda f: f[len(base):].split("/")[0] if "/" in f[len(base):] else "(root)"
    main = {u: collections.Counter(top(f) for f, x in unit.items() if x == u).most_common(1)[0][0] for u in size}
    sz = collections.Counter()
    for u, t in main.items():
        sz[t] += size[u]
    keep = {t for t, _ in sz.most_common(MAX - 1)} if len(sz) > MAX else set(sz)
    return {u: (t if t in keep else "other") for u, t in main.items()}


def m_louvain(size, sim, **_):
    w = {(a, b): sim(a, b) for a, b in itertools.combinations(sorted(size), 2) if sim(a, b)}
    best = None
    for res in (2.0, 1.5, 1.2, 1.0, 0.8, 0.6, 0.4, 0.2):
        c = roles.louvain(sorted(size), w, res)
        if len(set(c.values())) <= MAX:
            best = c
            break
    return best or {u: "all" for u in size}


def boxes(groups):
    return {u: g[0] for g in groups for u in g}


def m_size(unit, size, **_):
    keep = {u for u, _ in size.most_common(MAX - 1)}
    return {u: (u if u in keep else "other") for u in size}


METHODS = {
    "folders": lambda **k: m_folder(**k),
    "imports (Louvain)": lambda size, imp, **_: m_louvain(size, imp),  # = roles.suggest_areas
    "imports+co-change (Louvain)": lambda size, imp, co, **_: m_louvain(size, lambda a, b: imp(a, b) + co(a, b)),
    "imports+folders (Louvain)": lambda size, imp, fold, **_: m_louvain(size, lambda a, b: imp(a, b) + 0.5 * fold(a, b)),
    "imports (agglomerative)": lambda size, imp, **_: boxes(agglo(size, size, imp)),
    "largest + other": lambda **k: m_size(**k),
    "imports+folders+names": lambda size, imp, fold, words, **_: boxes(agglo(size, size, lambda a, b: imp(a, b) + 0.5 * fold(a, b) + 0.5 * words(a, b))),
    "co-change": lambda size, co, **_: boxes(agglo(size, size, co)),
    "co-change+imports+folders": lambda size, imp, fold, co, **_: boxes(agglo(size, size, lambda a, b: co(a, b) + imp(a, b) + 0.5 * fold(a, b))),
    "co-change+imports+folders, capped": lambda size, imp, fold, co, **_: boxes(agglo(size, size, lambda a, b: co(a, b) + imp(a, b) + 0.5 * fold(a, b), cap=CAP)),
    "roles.suggest_areas (shipped)": lambda unit, graph, train, **_: boxes(roles.suggest_areas(unit, roles.role_imports(graph, unit), train)),
    "imports+folders+names, capped": lambda size, imp, fold, words, **_: boxes(agglo(size, size, lambda a, b: imp(a, b) + 0.5 * fold(a, b) + 0.5 * words(a, b), cap=CAP)),
    "co-change+imports+folders+names, capped": lambda size, imp, fold, words, co, **_: boxes(agglo(size, size, lambda a, b: co(a, b) + imp(a, b) + 0.5 * fold(a, b) + 0.5 * words(a, b), cap=CAP)),
}


GROUP_SYSTEM = (
    "You group the functional roles of a software system into at most 7 areas, for a developer who will pick one area, "
    "then one role, and ask a coding agent to change it. A good area is one place a typical change stays inside: roles "
    "that import each other a lot and change together belong together; a role that most others use but that changes on "
    "its own can stay alone. No area should hold more than 40% of the files: a huge area fences nothing. Folders are "
    "hints, not rules. You get each role with its purpose, size and main folders, the imports between roles, and a "
    "suggested grouping computed from imports, the change history and folders. Keep that grouping unless the purposes "
    "show a clearly better one. Name each area in 1 to 3 lowercase words, in the project's own vocabulary, with one plain "
    "sentence of at most 20 words. Every role goes in exactly one area. Reply with JSON only: "
    "{\"areas\": [{\"name\": \"...\", \"purpose\": \"...\", \"roles\": [\"<role name>\", ...]}]}")


def group_prompt(store, role_of, imports, suggestion):
    rn = lambda rid: store["roles"][rid]["name"]
    lines = ["ROLES", roles.area_prompt(store, role_of, [[r] for r in sorted(set(role_of.values()))]).replace("AREA ", "#")]
    lines += ["", "IMPORT LINES BETWEEN ROLES (strongest first)"]
    lines += [f"- {' <-> '.join(sorted(rn(r) for r in k))}: {v}" for k, v in imports.most_common(40)]
    lines += ["", "SUGGESTED GROUPING (imports, change history, folders)"] + [f"- {', '.join(rn(r) for r in g)}" for g in suggestion]
    return "\n".join(lines)


def apply_areas(store, role_ids, answer):
    """The model's areas as {"a1": {name, purpose, roles}}, or ValueError when they are not a partition of role_ids
    into at most MAX named areas."""
    by_name = {store["roles"][r]["name"].casefold(): r for r in role_ids}
    areas, seen = {}, set()
    for i, a in enumerate((answer or {}).get("areas") or [], 1):
        rs = [by_name.get(str(n).casefold()) for n in a.get("roles") or []]
        if None in rs or seen & set(rs) or not rs:
            raise ValueError("the areas name an unknown role or a role twice")
        seen |= set(rs)
        areas[f"a{i}"] = {"name": roles.tidy(str(a.get("name") or f"area {i}")), "purpose": str(a.get("purpose") or "")[:200], "roles": rs}
    if seen != set(role_ids) or not 1 <= len(areas) <= MAX:
        raise ValueError(f"the areas must hold every role once, in at most {MAX} areas")
    return areas



def m_model(root, graph, unit, claude, model, evidence):
    """A model groups these units into areas, a grouping as evidence (an experiment; not shipped). (box map, cost)."""
    from modfence import purpose
    stored = roles.load_store(root) if roles.view(root, graph)["roles"] else None
    names = {u: (stored["roles"][u]["name"] if stored and u in stored["roles"] else u) for u in set(unit.values())}
    if stored:  # units are role names here; the store is keyed by id
        ids = {r["name"]: rid for rid, r in stored["roles"].items()}
        store = {"roles": {u: {"name": u, "purpose": stored["roles"][ids[u]].get("purpose", "")} for u in names}}
    else:  # roles.DEFAULT groups: the name is the folder or path word; the purpose is the first docstring found
        doc = {u: next((graph["files"][f]["doc"] for f, x in sorted(unit.items()) if x == u and graph["files"][f]["doc"]), "")
               for u in names}
        store = {"roles": {u: {"name": u, "purpose": doc[u][:120]} for u in names}}
    imports = roles.role_imports(graph, unit)
    groups = collections.defaultdict(list)
    for u, b in evidence.items():
        groups[b].append(u)
    suggestion = sorted(groups.values(), key=lambda g: (-len(g), g))
    answer, cost = purpose._ask(claude, group_prompt(store, unit, imports, suggestion), system=GROUP_SYSTEM, model=model)
    areas = apply_areas(store, sorted(names), answer)
    return {u: aid for aid, a in areas.items() for u in a["roles"]}, cost


def score(box, unit, test):
    n, bsize = len(unit), collections.Counter(box[u] for u in unit.values())
    one = cover = 0
    for c in test:
        bs = {box[unit[f]] for f in c}
        one += len(bs) == 1
        cover += sum(bsize[b] for b in bs) / n
    return {"boxes": len(set(box.values())), "one_box": one / len(test), "cover": cover / len(test),
            "net": (one - cover) / len(test), "largest": max(bsize.values()) / n}


def run(root, claude=None, model="sonnet"):
    graph = analyze.analyze(root)
    unit, how = units_of(root, graph)
    size = collections.Counter(unit.values())
    train, test = commits(root, set(unit))
    test = [c for c in test if len({unit[f] for f in c}) >= 2]  # a one-unit change fits any grouping: it tells nothing
    words = vec_sim(unit, roles.tokens)
    fold = vec_sim(unit, lambda f: ["/".join(f.split("/")[:2])])
    kw = dict(graph=graph, train=train, unit=unit, size=size, imp=import_sim(graph, unit), fold=fold, words=words, co=cochange_sim(unit, train))
    rows = {"units as they are": score({u: u for u in size}, unit, test)}
    for name, m in METHODS.items():
        rows[name] = score(m(**kw), unit, test)
        rows[name]["areas"] = None
    k = min(MAX, len(size))
    rnd = []
    for s in range(20):
        rng = random.Random(s)
        rnd.append(score({u: rng.randrange(k) for u in sorted(size)}, unit, test))
    rows["random (mean of 20)"] = {key: sum(r[key] for r in rnd) / 20 for key in rnd[0]}
    if claude:
        try:
            box, cost = m_model(root, graph, unit, claude, model, METHODS["roles.suggest_areas (shipped)"](**kw))
            rows[f"model ({model}), best grouping as evidence"] = dict(score(box, unit, test), cost_usd=cost)
        except Exception as e:  # recorded, not hidden
            rows[f"model ({model}), best grouping as evidence"] = {"error": repr(e)[:300]}
    for r in rows.values():
        r.pop("areas", None)
    return {"repo": os.path.basename(os.path.abspath(root)), "units": len(size), "units_from": how,
            "files": len(unit), "train_commits": len(train), "test_commits": len(test), "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--model", default="", help="also ask this model (sonnet, haiku) to group the roles (an experiment; modfence ships the deterministic grouping)")
    a = ap.parse_args()
    from modfence import runner
    claude = runner.find_claude() if a.model else None
    out = []
    for root in a.repos:
        r = run(root, claude, a.model or "sonnet")
        out.append(r)
        print(f"\n{r['repo']}: {r['units']} units ({r['units_from']}), {r['files']} files, "
              f"{r['train_commits']} train / {r['test_commits']} test commits")
        print(f"  {'method':30} {'boxes':>5} {'one_box':>8} {'cover':>7} {'net':>6} {'largest':>8}")
        for name, s in r["rows"].items():
            if "error" in s:
                print(f"  {name:30} ERROR {s['error']}")
                continue
            print(f"  {name:30} {s['boxes']:5.1f} {s['one_box']:8.2f} {s['cover']:7.2f} {s['net']:6.2f} {s['largest']:8.2f}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
