"""The project's own docs, placed on the map (golden rules 3, 5 and 7).

A project's markdown files (README.md, design notes, runbooks) stay where they are, in git. modfence only works out
which box of the map each one is about, so that:
  - the side bar shows a box's docs with their size and how stale they are;
  - a run fenced to a box gets pointers to those docs (paths and titles, not their text: the agent reads what it needs,
    which costs tokens only when it helps);
  - a lesson learned in a run can be written into the box's doc.

A doc goes on the roles whose files it names (a path, or a file name found once in the project) and on the roles
whose files sit in its own folder; at most TOP per doc. The user can add or remove a doc on a box or on a link; those
choices are stored in .modfence/docs.json and win over the automatic ones. Deterministic, no model call.
"""
import json, os, re, subprocess, time
from collections import Counter, defaultdict

TOP = 3
SKIP = ("node_modules/", ".modfence/", ".git/", ".venv/", "venv/")


def _store_path(root):
    return os.path.join(root, ".modfence", "docs.json")


def load_choices(root):
    try:
        with open(_store_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_choices(root, d):
    os.makedirs(os.path.join(root, ".modfence"), exist_ok=True)
    with open(_store_path(root), "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, indent=1, sort_keys=True)


def markdown_files(root):
    """Project markdown files, git-tracked when the project is a git repo, else found on disk; hidden folders skipped."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "*.md", "**/*.md"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30)
        files = sorted({l.strip() for l in out.stdout.splitlines() if l.strip()}) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        files = None
    if files is None:
        files = []
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"]
            files += [os.path.relpath(os.path.join(d, n), root).replace("\\", "/") for n in names if n.endswith(".md")]
    return [f for f in sorted(files) if not f.startswith(".") and "/." not in f and not f.startswith(SKIP)]


def last_changed(root, limit=5000):
    """{path: unix time of the last commit that touched it}, from one git log; {} without git."""
    try:
        out = subprocess.run(["git", "-C", root, "log", f"-{limit}", "--name-only", "--format=%x1e%ct"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    seen = {}
    for chunk in out.split("\x1e")[1:]:
        lines = chunk.strip().splitlines()
        if not lines:
            continue
        t = int(lines[0])
        for p in lines[1:]:
            seen.setdefault(p.strip(), t)  # newest first, so the first time a path appears is its last change
    return seen


def _title(text, path):
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()[:100]
    return os.path.basename(path)


def mentions(text, code_files):
    """Code files a doc names: by path, or by a file name that is unique in the project and at least 5 letters long."""
    by_name = defaultdict(list)
    for f in code_files:
        by_name[os.path.basename(f)].append(f)
    found = {f for f in code_files if f in text}
    for word in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}\.py", text)):
        if len(by_name.get(word, ())) == 1:
            found.add(by_name[word][0])
    return found


def view(root, role_of):
    """{"docs": [{path, title, lines, tokens, changed, stale, names, boxes, auto}], "links": {link key: [paths]}}.
    role_of: {code file: role id}. boxes are "role:<id>" (automatic, then the user's additions, minus their removals);
    stale counts the code files a doc names that changed after the doc's own last change (N/A, None, without git)."""
    choices, changed = load_choices(root), last_changed(root)
    code = sorted(role_of)
    files_in = defaultdict(Counter)
    for f, r in role_of.items():
        files_in[os.path.dirname(f)][r] += 1
    out, links = [], defaultdict(list)
    for path in markdown_files(root):
        try:
            with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        named = mentions(text, code)
        score = Counter(role_of[f] for f in named)
        folder = os.path.dirname(path)
        for d, rs in files_in.items():  # the doc's own folder and those below it
            if folder and (d == folder or d.startswith(folder + "/")):
                for r, n in rs.items():
                    score[r] += 0.5 * n
        auto = [f"role:{r}" for r, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]]
        mine = choices.get(path, {})
        boxes = [b for b in auto if b not in mine.get("remove", [])] + [b for b in mine.get("add", []) if b not in auto]
        for b in boxes:
            if b.startswith("link:"):
                links[b].append(path)
        t = changed.get(path)
        stale = None if t is None else sum(1 for f in named if changed.get(f, 0) > t)
        out.append({"path": path, "title": _title(text, path), "lines": text.count("\n") + 1, "tokens": len(text) // 4,
                    "changed": t, "stale": stale, "names": len(named), "boxes": boxes, "auto": auto})
    return {"docs": out, "links": dict(links)}


def choose(root, path, box, on):
    """The user puts a doc on a box or link (on=True) or takes it off (on=False)."""
    d = load_choices(root)
    c = d.setdefault(path, {"add": [], "remove": []})
    for k in ("add", "remove"):
        c[k] = [b for b in c.get(k, []) if b != box]
    c["add" if on else "remove"].append(box)
    save_choices(root, d)


def for_fence(root, role_of, scope_files, areas=None):
    """[(path, title, lines)] of the docs on the roles a fence covers, or on links that touch them: pointers for the run."""
    fenced = {f"role:{role_of[f]}" for f in scope_files if f in role_of}
    v = view(root, role_of)
    hits = []
    for d in v["docs"]:
        on_box = fenced & set(d["boxes"])
        on_link = any(b.startswith("link:") and (fenced & set(b[5:].split("|"))) for b in d["boxes"])
        if on_box or on_link:
            hits.append((d["path"], d["title"], d["lines"]))
    return hits


def safe_doc(root, path):
    """The absolute path of a markdown file inside root, or ValueError."""
    full = os.path.realpath(os.path.join(root, path))
    if not path.endswith(".md") or not full.startswith(os.path.realpath(root) + os.sep):
        raise ValueError("only markdown files inside the project")
    return full


def add_lesson(root, path, text):
    """Append a dated line under '## Gotchas' (created at the end if missing). The doc is the project's own file."""
    full = safe_doc(root, path)
    line = f"- {text.strip()} ({time.strftime('%Y-%m-%d')})\n"
    try:
        with open(full, encoding="utf-8") as f:
            body = f.read()
    except OSError:
        body = f"# {os.path.splitext(os.path.basename(path))[0]}\n"
    if "\n## Gotchas\n" in "\n" + body:
        head, _, rest = body.partition("## Gotchas\n")
        nxt = re.search(r"^## ", rest, re.M)
        cut = nxt.start() if nxt else len(rest)
        body = head + "## Gotchas\n" + rest[:cut].rstrip("\n") + "\n" + line + ("\n" + rest[cut:] if nxt else "")
    else:
        body = body.rstrip("\n") + "\n\n## Gotchas\n" + line
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
