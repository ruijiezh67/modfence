"""Score modfence's role-grouping methods.

python bench/roles_eval.py PROJECT [REFERENCE.json] [--out DIR]

Without a reference it reports structure only. A reference is {"files": {path: {"role": name}}} built from the
project's own docs, never from these methods (see the run's notes for how). Metrics:

Against the reference (on the files it assigns):
  ARI   adjusted Rand index (Hubert & Arabie 1985): pair agreement corrected for chance; 1 = same partition, ~0 = random.
  NMI   normalized mutual information, arithmetic-mean normalization (Strehl & Ghosh 2002).
  F1    pairwise: precision = pairs grouped together by both / by the method; recall = ... / by the reference.
  MoJoFM is the field's usual third metric; it is not implemented here (N/A).
Structure (all code files, no reference needed):
  MQ    Bunch's TurboMQ divided by the number of groups: mean over groups of 2*inside / (2*inside + crossing)
        import lines (Mitchell & Mancoridis 2006); higher = more cohesive, less coupled.
  coupling  share of import lines that cross groups ("shared" excluded); lower is better (Stevens, Myers &
        Constantine 1974: low coupling, high cohesion).
  cyclic    groups that sit in a dependency cycle with another group (Martin's Acyclic Dependencies Principle).
  stability ARI between the grouping of all files and the grouping with 10% of files removed, mean of 5 seeds.
"""
import argparse, json, math, os, random, sys, time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence import analyze, roles  # noqa: E402


def contingency(a, b, items):
    return Counter((a[i], b[i]) for i in items)


def ari(a, b, items):
    c2 = lambda n: n * (n - 1) / 2
    tab = contingency(a, b, items)
    sa, sb = Counter(a[i] for i in items), Counter(b[i] for i in items)
    idx = sum(c2(v) for v in tab.values())
    ea, eb, n = sum(c2(v) for v in sa.values()), sum(c2(v) for v in sb.values()), c2(len(items))
    exp = ea * eb / n if n else 0
    mx = (ea + eb) / 2
    return 1.0 if mx == exp else (idx - exp) / (mx - exp)


def nmi(a, b, items):
    n = len(items)
    tab = contingency(a, b, items)
    sa, sb = Counter(a[i] for i in items), Counter(b[i] for i in items)
    h = lambda c: -sum(v / n * math.log(v / n) for v in c.values())
    mi = sum(v / n * math.log(v * n / (sa[x] * sb[y])) for (x, y), v in tab.items())
    d = (h(sa) + h(sb)) / 2
    return 1.0 if d == 0 else mi / d


def pair_f1(a, b, items):
    c2 = lambda n: n * (n - 1) / 2
    both = sum(c2(v) for v in contingency(a, b, items).values())
    pa = sum(c2(v) for v in Counter(a[i] for i in items).values())
    pb = sum(c2(v) for v in Counter(b[i] for i in items).values())
    p, r = (both / pa if pa else 0), (both / pb if pb else 0)
    return p, r, (2 * p * r / (p + r) if p + r else 0)


def directed_edges(graph, files):
    keep, w, allf = set(files), Counter(), set(graph["files"])
    for f in files:
        r = analyze._parse(os.path.join(graph["root"], f), f)
        for t, *_ in analyze._resolved(f, r["imports"], allf):
            if t in keep and t != f:
                w[(f, t)] += 1
    return w


def structure(groups, edges):
    inside, cross, out = Counter(), Counter(), defaultdict(set)
    for (a, b), v in edges.items():
        ga, gb = groups[a], groups[b]
        if ga == gb:
            inside[ga] += v
        else:
            cross[ga] += v
            cross[gb] += v
            if roles.SHARED not in (ga, gb):
                out[ga].add(gb)
    gs = set(groups.values())
    mq = sum(2 * inside[g] / (2 * inside[g] + cross[g]) for g in gs if inside[g] + cross[g]) / len(gs)
    real = {e: v for e, v in edges.items() if roles.SHARED not in (groups[e[0]], groups[e[1]])}
    tot = sum(real.values())
    coupling = sum(v for (a, b), v in real.items() if groups[a] != groups[b]) / tot if tot else 0
    sizes = Counter(groups.values())
    return {"groups": len(gs), "largest": max(sizes.values()) / len(groups), "singletons": sum(1 for v in sizes.values() if v == 1),
            "shared": sizes.get(roles.SHARED, 0), "MQ": mq, "coupling": coupling, "cyclic": len(_cyclic(out))}


def _cyclic(out):
    """Nodes in a strongly connected component of size > 1 (Tarjan)."""
    index, low, stack, on, res, n = {}, {}, [], set(), set(), [0]
    sys.setrecursionlimit(10000)

    def visit(v):
        index[v] = low[v] = n[0]; n[0] += 1; stack.append(v); on.add(v)
        for w in out.get(v, ()):
            if w not in index:
                visit(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop(); on.discard(w); comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                res.update(comp)
    for v in sorted(set(out) | {w for ws in out.values() for w in ws}):
        if v not in index:
            visit(v)
    return res


def stability(fn, graph, files, seeds=5):
    full = fn(graph, files)
    vals = []
    for s in range(seeds):
        sub = sorted(random.Random(s).sample(files, int(len(files) * 0.9)))
        vals.append(ari(full, fn(graph, sub), sub))
    return sum(vals) / len(vals)


def variants():
    """The methods, plus a small sweep of the hybrid's knobs (named so the table says what was tried)."""
    v = dict(roles.METHODS)
    v["folder2"] = lambda g, f=None: roles.by_folder(g, f, depth=2)
    for res in (0.5, 2.0):
        v[f"imports r{res}"] = lambda g, f=None, res=res: roles.by_imports(g, f, resolution=res)
    for wf, ww, res in ((0.5, 0, 1.0), (0, 1.0, 1.0), (1.0, 1.0, 1.0), (0.5, 1.0, 2.0), (0.5, 2.0, 1.0)):
        v[f"hybrid f{wf} w{ww} r{res}"] = lambda g, f=None, wf=wf, ww=ww, res=res: roles.by_hybrid(g, f, w_folder=wf, w_word=ww, resolution=res)
    for wf, ww in ((0.5, 1.0), (1.0, 1.0)):
        v[f"anchored f{wf} w{ww}"] = lambda g, f=None, wf=wf, ww=ww: roles.by_hybrid(g, f, w_folder=wf, w_word=ww, anchored=True)
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("reference", nargs="?")
    ap.add_argument("--out", help="folder for results.json and results.md (keep private projects' results private)")
    a = ap.parse_args()
    graph = analyze.analyze(a.project)
    files = roles.code_files(graph)
    edges = directed_edges(graph, files)
    ref = None
    if a.reference:
        ref = {p: v["role"] for p, v in json.load(open(a.reference, encoding="utf-8"))["files"].items()}
    rows = []
    for name, fn in variants().items():
        t = time.time()
        g = fn(graph, files)
        row = {"method": name, "seconds": round(time.time() - t, 2), **structure(g, edges), "stability": stability(fn, graph, files)}
        if ref:
            items = sorted(set(ref) & set(g))
            p, r, f1 = pair_f1(g, ref, items)
            row.update(scored=len(items), ARI=ari(g, ref, items), NMI=nmi(g, ref, items), P=p, R=r, F1=f1)
        rows.append(row)
        print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}), flush=True)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        json.dump({"project": os.path.basename(os.path.abspath(a.project)), "files": len(files), "edges": sum(edges.values()),
                   "reference": bool(ref), "rows": rows}, open(os.path.join(a.out, "results.json"), "w"), indent=1)
        cols = ["method", "groups", "largest", "MQ", "coupling", "cyclic", "stability"] + (["ARI", "NMI", "F1"] if ref else [])
        fmt = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)
        md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows]
        open(os.path.join(a.out, "results.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
