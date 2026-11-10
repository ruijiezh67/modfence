"""The map as text for any AI agent (golden rules 3, 5 and 7): paste it into Cursor, Codex or a new session so the agent
starts from the project's shape instead of exploring it.

One project-level text, deterministic and capped (BUDGET characters, about 1.5k tokens): the functions and their roles,
the strongest links between functions with their kind, copies to keep in sync, read-only files, the test command, the
last runs and which docs cover which function. Built from what modfence already computed; no model call. A box's own
brief (what it uses, what others use from it) is brief.brief, offered next to it.
"""
import os, time
from collections import Counter, defaultdict

BUDGET = 6000  # characters, about 1.5k tokens: the same cap as a fence's brief
ROLES_PER_FUNCTION, LINKS, RUNS, DOCS = 6, 12, 5, 3


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def build(root, graph):
    """The handoff text, or a short note when the project has no functions yet."""
    from . import docs as docs_mod, roles, runner
    v = roles.view(root, graph)
    name = os.path.basename(os.path.abspath(root))
    if not v["roles"] or not v.get("areas"):
        return (f"# {name}: no module map yet\nOpen the project in modfence once so it can group the code into "
                "functions, then copy the map again.")
    rid_name = {r["id"]: r["name"] for r in v["roles"]}
    role_files = {r["id"]: [f for f in r["files"] if f not in v["kinds"]] for r in v["roles"]}
    fn_of = {rid: a["name"] for a in v["areas"] for rid in a["roles"]}
    file_fn = {f: fn_of.get(rid) for rid, fs in role_files.items() for f in fs}
    for f, rid in v["doors"].items():
        file_fn.setdefault(f, fn_of.get(rid))

    out = [f"# {name}: module map for AI agents (modfence, {time.strftime('%Y-%m-%d')})",
           "Work on one function at a time. Ask before editing files of another function."]
    out.append("\n## Functions")
    for a in v["areas"]:
        rs = [r for r in a["roles"] if role_files.get(r)]
        n = sum(len(role_files[r]) for r in rs)
        top = Counter(os.path.dirname(f) or "." for r in rs for f in role_files[r]).most_common(2)
        out.append(f"- {a['name']} ({_plural(n, 'file')}; {', '.join(d + '/' for d, _ in top)}): {a.get('purpose') or ''}".rstrip(": "))
        out.append("  roles: " + ", ".join(f"{rid_name[r]} ({len(role_files[r])})" for r in sorted(rs, key=lambda r: -len(role_files[r]))[:ROLES_PER_FUNCTION])
                   + (f", +{len(rs) - ROLES_PER_FUNCTION} more" if len(rs) > ROLES_PER_FUNCTION else ""))

    # links between functions: imports by import lines, HTTP routes, copies
    imports, http, copies = Counter(), defaultdict(set), Counter()
    for e in graph["edges"]:
        for r in e["receipts"]:
            a, b = file_fn.get(r["file"]), file_fn.get(r.get("target_file"))
            if a and b and a != b:
                imports[(a, b)] += 1
    for l in v.get("links") or []:
        a, b = file_fn.get(l["file"]), file_fn.get(l["target_file"])
        if a and b and a != b:
            if l["kind"] == "http":
                http[(a, b)].add(l["name"])
            elif l["kind"] == "copy":
                copies[tuple(sorted((a, b)))] += 1
    links = [(n, f"{a} -> {b}: imports ({n} lines)") for (a, b), n in imports.items()]
    links += [(len(s), f"{a} -> {b}: calls {_plural(len(s), 'HTTP route')} ({', '.join(sorted(s)[:3])})") for (a, b), s in http.items()]
    if links:
        out.append("\n## Links between functions (A -> B: A depends on B; changing B can break A)")
        out += [t for _, t in sorted(links, key=lambda x: (-x[0], x[1]))[:LINKS]]
    if copies:
        out.append("\n## Keep in sync (copied code: a fix in one belongs in the other)")
        out += [f"{a} <-> {b}: {_plural(n, 'copied file')}" for (a, b), n in copies.most_common(5)]

    ro = sorted(f for f, k in v["kinds"].items() if k == "shared")
    entries = sorted(f for f, k in v["kinds"].items() if k == "entry")
    if ro or entries:
        out.append("\n## Read-only unless asked")
        if ro:
            out.append("shared config: " + ", ".join(ro[:8]))
        if entries:
            out.append("entry points: " + ", ".join(entries[:8]) + (" ..." if len(entries) > 8 else ""))

    cmd = runner.test_command(root)
    if cmd:
        out.append("\n## Tests\n" + (cmd if isinstance(cmd, str) else " ".join(["python"] + list(cmd[1:]))))

    runs = runner.versions(root)[-RUNS:]
    if runs:
        out.append("\n## Recent changes (newest last)")
        for r in runs:
            fns = sorted({file_fn.get(f["path"]) for f in r.get("files") or [] if file_fn.get(f["path"])})
            msg = (r.get("commit_message") or r.get("prompt") or "").splitlines()[0][:100]
            out.append(f"{time.strftime('%m-%d', time.localtime(r.get('at') or 0))} [{', '.join(fns) or 'other files'}] {msg}")

    try:
        d = docs_mod.view(root, {f: rid for rid, fs in role_files.items() for f in fs})["docs"]
    except OSError:
        d = []
    by_fn = defaultdict(list)
    for doc in sorted(d, key=lambda x: x["lines"]):
        for b in doc["boxes"]:
            fname = fn_of.get(b[5:]) if b.startswith("role:") else None
            if fname and doc["path"] not in by_fn[fname]:
                by_fn[fname].append(doc["path"])
    if by_fn:
        out.append("\n## Docs to read before changing a function (shortest first)")
        out += [f"{k}: {', '.join(p[:DOCS])}" for k, p in sorted(by_fn.items())]

    text = "\n".join(out)
    if len(text) > BUDGET:  # ponytail: cut whole lines from the end; the functions come first and survive
        cut = text[:BUDGET].rsplit("\n", 1)[0]
        text = cut + "\n(cut to stay under about 1.5k tokens)"
    return text
