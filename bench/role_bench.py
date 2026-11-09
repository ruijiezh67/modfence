"""Which way of grouping files into roles fits vibe coding? (golden rules 4, 6; the level you usually fence)

A role is good to fence when a real change that touches several files stays inside one role. Methods give different
numbers and sizes of roles, and smaller roles fit fewer changes by chance alone, so each method is compared with its
own floor: the same files shuffled among groups of the same sizes (20 seeds).

  one_role  share of held-out multi-file commits whose files all lie in one role
  lift      one_role minus the shuffled floor (higher: the grouping itself keeps changes together)
  cover     mean share of code files inside the roles a commit touches (lower: tighter fence)
  groups, tiny, largest   how many roles, how many hold under 2% of the files, the biggest role's share

Files: code files (roles.code_files) minus entry points, doors and shared config. Commits: newest 30% held out, kept
when they change 2 to 30 of these files; the co-change method learns only from the older 70%.

Usage: python bench/role_bench.py REPO [REPO ...] [--json OUT]
"""
import argparse, collections, json, math, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence import analyze, roles  # noqa: E402
from area_bench import commits  # noqa: E402

SEEDS = 20


def cochange_merge(graph, groups, train, resolution=1.0):
    """folder_words groups merged by Louvain on imports between them plus how often they changed together (train)."""
    w = collections.Counter()
    for (a, b), v in roles.intra_module_edges(graph, list(groups)).items():
        ga, gb = groups[a], groups[b]
        if ga != gb:
            w[(min(ga, gb), max(ga, gb))] += 1 + math.log(v)
    for c in train:
        gs = sorted({groups[f] for f in c if f in groups})
        for i, a in enumerate(gs):
            for b in gs[i + 1:]:
                w[(a, b)] += 2.0 / (len(gs) - 1)  # a commit spread over many groups says little about each pair
    nodes = sorted(set(groups.values()))
    comm = roles.louvain(nodes, dict(w), resolution)
    size = collections.Counter(groups.values())
    name = {c: max((g for g in nodes if comm[g] == c), key=lambda g: (size[g], g)) for c in set(comm.values())}
    return {f: name[comm[g]] for f, g in groups.items()}


def score(group, test):
    n, gsize = len(group), collections.Counter(group.values())
    one = cover = 0
    for c in test:
        gs = {group[f] for f in c}
        one += len(gs) == 1
        cover += sum(gsize[g] for g in gs) / n
    return one / len(test), cover / len(test)


def shuffled(group, test):
    files, labels = sorted(group), [group[f] for f in sorted(group)]
    out = []
    for s in range(SEEDS):
        lab = labels[:]
        random.Random(s).shuffle(lab)
        out.append(score(dict(zip(files, lab)), test)[0])
    return sum(out) / SEEDS


def run(root):
    graph = analyze.analyze(root)
    code = roles.code_files(graph)
    kind, _ = roles.kinds(graph, roles.by_folder(graph, code))
    files = [f for f in code if f not in kind]
    train, test = commits(root, set(files))
    test = [c for c in test if len(c) >= 2]
    methods = {name: (lambda m=m: m(graph, files)) for name, m in roles.METHODS.items()}
    methods["folder_words, merged by co-change + imports"] = lambda: cochange_merge(graph, roles.by_folder_words(graph, files), train)
    methods["history"] = lambda: roles.by_history(graph, files, changes=train)  # shipped; learns from older commits only
    methods["history, no top-folder pull"] = lambda: roles.by_history(graph, files, changes=train, top_w=0)
    fw = roles.by_folder_words(graph, files)
    for k in (10, 15):  # the area algorithm one level down: co-change + imports + folders, no role over 25% of the files
        methods[f"folder_words, agglomerated to {k} (co-change+imports+folders, cap 25%)"] = (
            lambda k=k: {f: f"g{i}" for i, grp in enumerate(roles.suggest_areas(fw, roles.role_imports(graph, fw), train, most=k, cap=0.25))
                         for u in grp for f, x in fw.items() if x == u})
    v = roles.view(root, graph)
    if v["roles"]:
        stored = {f: r["name"] for r in v["roles"] for f in r["files"]}
        methods["stored roles (model-named)"] = lambda: {f: stored.get(f, "?") for f in files}
    rows = {}
    for name, m in methods.items():
        g = m()
        g = {f: g.get(f, "?") for f in files}
        one, cover = score(g, test)
        sizes = collections.Counter(g.values())
        rows[name] = {"groups": len(sizes), "largest": max(sizes.values()) / len(g), "one_role": one,
                      "tiny": sum(1 for v in sizes.values() if v < 0.02 * len(g)),
                      "floor": shuffled(g, test), "cover": cover}
        rows[name]["lift"] = rows[name]["one_role"] - rows[name]["floor"]
    return {"repo": os.path.basename(os.path.abspath(root)), "files": len(files), "train_commits": len(train),
            "test_commits": len(test), "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    out = []
    for root in a.repos:
        r = run(root)
        out.append(r)
        print(f"\n{r['repo']}: {r['files']} files, {r['train_commits']} train / {r['test_commits']} test commits")
        print(f"  {'method':44} {'groups':>6} {'tiny':>5} {'largest':>8} {'one_role':>9} {'floor':>6} {'lift':>6} {'cover':>6}")
        for name, s in sorted(r["rows"].items(), key=lambda kv: -kv[1]["lift"]):
            print(f"  {name:44} {s['groups']:6d} {s['tiny']:5d} {s['largest']:8.2f} {s['one_role']:9.2f} {s['floor']:6.2f} {s['lift']:6.2f} {s['cover']:6.2f}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
