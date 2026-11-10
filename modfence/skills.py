"""Find agent skills that fit this project, and install one into the project only when the user asks.

The stack is read from the code and the manifests, with no model call: the third-party packages the project's files
import, and the dependencies its requirements*.txt, pyproject.toml and package.json list. Each library is searched on
skills.sh (the endpoint `npx skills find` uses), and a hit is kept only with 1000+ installs and, when its repo's stars
can be read, 100+ stars (the find-skills quality bar). Network is used only in search, stars and install.
An install writes one skill folder under <project>/.claude/skills/; nothing is installed globally and nothing
downloaded is ever run.
"""
import json, os, re, shutil, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

from . import analyze, roles

SEARCH = "https://skills.sh/api/search?q="
GITHUB = "https://api.github.com/repos/"
RAW = "https://raw.githubusercontent.com/"
DAY = 86400
MIN_INSTALLS, MIN_STARS, MOST, TOP_LIBS, PER_WORD = 1000, 100, 12, 8, 3
MAX_FILES, MAX_BYTES = 200, 5_000_000  # one skill folder; a bigger one is refused
# import name -> the word people search for (only where they differ)
ALIAS = {"PIL": "pillow", "cv2": "opencv", "sklearn": "scikit-learn", "yaml": "pyyaml", "bs4": "beautifulsoup",
         "objc": "pyobjc", "AppKit": "pyobjc", "Foundation": "pyobjc", "Quartz": "pyobjc", "Cocoa": "pyobjc"}
try:
    import tomllib
except ImportError:  # Python 3.10: pyproject.toml is skipped
    tomllib = None


def _get(url):
    """Bytes at url. No cookies, no credentials, no personal data: only a User-Agent."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "modfence"}), timeout=10) as r:
        return r.read()


# ---------- the project's stack ----------

def _manifests(root):
    """{dependency name: manifest file} from requirements*.txt, pyproject.toml and package.json at the root."""
    out = {}
    for f in sorted(os.listdir(root)):
        full = os.path.join(root, f)
        try:
            if re.fullmatch(r"requirements.*\.txt", f):
                for line in analyze.read_text(full).splitlines():
                    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
                    if m:
                        out.setdefault(m.group(1), f)
            elif f == "pyproject.toml" and tomllib:
                d = tomllib.loads(analyze.read_text(full))
                p = d.get("project", {})
                specs = p.get("dependencies", []) + [s for v in p.get("optional-dependencies", {}).values() for s in v]
                names = [re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", s) for s in specs]
                names = [m.group(1) for m in names if m] + list(d.get("tool", {}).get("poetry", {}).get("dependencies", {}))
                for n in names:
                    if n.lower() != "python":
                        out.setdefault(n, f)
            elif f == "package.json":
                d = json.loads(analyze.read_text(full))
                for n in list(d.get("dependencies", {})) + list(d.get("devDependencies", {})):
                    out.setdefault(n, f)
        except (OSError, ValueError, AttributeError, TypeError):
            continue  # a manifest that cannot be read adds nothing
    return out


def _ranked(counter):
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))  # most first, ties by name: deterministic


def stack(root, graph):
    """{"libs": {import name: files importing it}, "manifests": {dependency: manifest file},
    "groups": {role or module: [[lib, files], ...top 5]}, "group_kind": "role" | "module"}."""
    files = set(graph["files"])
    # any folder or module name anywhere in the project is its own code: projects that put backend/ on sys.path
    # import "kernel" for backend/kernel, which is not a third-party library
    own = {part.removesuffix(".py") for p in files for part in p.split("/")}
    used = {}
    for p in sorted(files):
        names = set()
        for parts, _, _, _ in analyze._parse(os.path.join(root, p), p)["imports"]:
            top = parts[0] if parts else ""
            if (top and top not in own and top not in sys.stdlib_module_names and not top.startswith("_")
                    and not analyze._resolve(parts, files, p.split("/")[:-1], graph.get("roots", ()))[0]):
                names.add(top)
        used[p] = names
    store = roles.load_store(root) or {}
    role_name = {rid: r.get("name", rid) for rid, r in (store.get("roles") or {}).items()}
    by_role = {f: role_name[rid] for f, rid in (store.get("files") or {}).items() if rid in role_name}
    group = {p: by_role.get(p) or graph["files"][p]["module"] for p in files}
    per = defaultdict(Counter)
    for p, names in used.items():
        per[group[p]].update(names)
    libs = Counter(n for names in used.values() for n in names)
    return {"libs": dict(_ranked(libs)), "manifests": _manifests(root),
            "groups": {g: [list(x) for x in _ranked(c)[:5]] for g, c in sorted(per.items()) if c},
            "group_kind": "role" if by_role else "module"}


def queries(st, graph):
    """[(search word, files using it, reason)], strongest first: imported libraries, then manifest-only
    dependencies, then the project's tasks."""
    out, seen = [], set()
    for lib, n in list(st["libs"].items())[:TOP_LIBS]:
        word = ALIAS.get(lib, lib).lower()
        if word not in seen:
            seen.add(word)
            gs = [g for g, top in st["groups"].items() if any(x == lib for x, _ in top)]
            where = f" in {gs[0]}" + (f" and {len(gs) - 1} more" if len(gs) > 1 else "") if gs else ""
            out.append((word, n, f"used by {n} file{'s' * (n != 1)}{where}: {lib}"))
    for dep, f in st["manifests"].items():
        word = ALIAS.get(dep, dep).lower()
        if word not in seen and len(out) < TOP_LIBS + 4:
            seen.add(word)
            out.append((word, 0, f"listed in {f}: {dep}"))
    tests = [m for m in graph["modules"] if m["kind"] == "tests"]
    if tests:
        out.append(("python testing", 0, f"project has tests: {tests[0]['id']}"))
    return out


# ---------- skills.sh and GitHub ----------

def search(query):
    """([{id, name, source, installs, description, url}], error text or None). description is None: the search
    API does not return one."""
    try:
        d = json.loads(_get(SEARCH + urllib.parse.quote(query)))
        return [{"id": s["id"], "name": s["name"], "source": s.get("source") or "", "installs": int(s.get("installs") or 0),
                 "description": None, "url": "https://skills.sh/" + s["id"]} for s in d.get("skills", [])], None
    except Exception as e:  # network, HTTP or a changed response: no results, and say why
        return [], f"search {query!r}: {type(e).__name__}: {e}"


def _cache(root):
    try:
        with open(os.path.join(root, ".modfence", "skills_cache.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(root, c):
    from .runner import state_dir, write_text
    write_text(os.path.join(state_dir(root), "skills_cache.json"), json.dumps(c, indent=1))


def stars(source):
    """Stars of a GitHub repo "owner/name", or None when it cannot be read (rate limit, network, not found)."""
    try:
        return int(json.loads(_get(GITHUB + source))["stargazers_count"])
    except Exception:
        return None


def recommend(root, graph, refresh=False):
    """{"skills": [{..search fields, stars, query, reason, match: "name" | "fuzzy"}], "queries", "errors", "at"}:
    at most MOST skills that pass the bar, at most PER_WORD per search word, ranked by match strength (every search
    word is in the skill's name, then files using the library), then installs. Cached in .modfence/skills_cache.json
    for a day, keyed by the search words."""
    cache = _cache(root)
    qs = queries(stack(root, graph), graph)
    words = [w for w, _, _ in qs]
    old = cache.get("recommend") or {}
    if not refresh and old.get("words") == words and time.time() - old.get("at", 0) < DAY:
        return old["result"]
    hits, errors = {}, []
    for word, n, reason in qs:
        found, err = search(word)
        if err:
            errors.append(err)
        for s in found:
            if s["installs"] < MIN_INSTALLS:
                continue
            strength = (all(t in s["name"].lower() for t in word.split()), n)
            if s["id"] not in hits or strength > hits[s["id"]][0]:
                hits[s["id"]] = (strength, dict(s, query=word, reason=reason, match="name" if strength[0] else "fuzzy"))
    star_cache = cache.setdefault("stars", {})
    kept, per_word = [], Counter()
    for _, s in sorted(hits.values(), key=lambda h: (not h[0][0], -h[0][1], -h[1]["installs"], h[1]["id"])):
        if len(kept) >= MOST:
            break
        if per_word[s["query"]] >= PER_WORD:  # one popular library does not fill the list
            continue
        st = None
        if s["source"]:
            at, st = star_cache.get(s["source"], [0, None])
            if time.time() - at >= DAY:
                st = stars(s["source"])
                if st is not None:
                    star_cache[s["source"]] = [time.time(), st]
            if st is not None and st < MIN_STARS:
                continue
        kept.append(dict(s, stars=st))  # stars None: could not be read, shown as N/A
        per_word[s["query"]] += 1
    result = {"skills": kept, "queries": words, "errors": errors, "at": time.time()}
    if not errors:  # a failed search is retried next time, not cached for a day
        cache["recommend"] = {"words": words, "at": result["at"], "result": result}
    _save_cache(root, cache)
    return result


# ---------- the project's own skills ----------

def skills_dir(root):
    return os.path.join(os.path.abspath(root), ".claude", "skills")


def installed(root):
    """Names of the skills in <root>/.claude/skills (folders holding a SKILL.md)."""
    d = skills_dir(root)
    return sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "SKILL.md"))) if os.path.isdir(d) else []


def view(root, graph, refresh=False):
    """GET /api/skills: recommendations, the stack they came from, and what is installed."""
    rec, have = recommend(root, graph, refresh), installed(root)
    return dict(rec, skills=[dict(s, installed=s["name"] in have) for s in rec["skills"]],
                stack=stack(root, graph), installed=have)


def install(root, source, skill, replace=False, fetch=None):
    """Download one skill folder (the folder named `skill` that holds a SKILL.md) from GitHub repo `source` into
    <root>/.claude/skills/<skill>/. Everything downloaded is data: paths are checked to stay inside that folder and
    nothing is run. Returns the relative paths written."""
    fetch = fetch or _get
    if (not re.fullmatch(r"[\w.-]+/[\w.-]+", source or "") or not re.fullmatch(r"[\w.-]+", skill or "")
            or not all(x.strip(".") for x in source.split("/") + [skill])):
        raise ValueError("source must be owner/repo and skill a plain folder name")
    dest = os.path.join(skills_dir(root), skill)
    if os.path.exists(dest) and not replace:
        raise FileExistsError(f"{skill} is already installed in this project")
    tree = json.loads(fetch(f"{GITHUB}{source}/git/trees/HEAD?recursive=1")).get("tree", [])
    blobs = {t["path"]: t.get("size", 0) for t in tree if t.get("type") == "blob" and isinstance(t.get("path"), str)}
    homes = [p[:-len("SKILL.md")].rstrip("/") for p in blobs if p == "SKILL.md" or p.endswith("/SKILL.md")]
    named = [h for h in homes if h.rsplit("/", 1)[-1] == skill] or (homes if homes == [""] else [])
    if not named:
        raise LookupError(f"no folder {skill!r} with a SKILL.md in {source}")
    home = min(named, key=len)
    rels = {p[len(home) + 1:] if home else p: p for p in blobs if not home or p.startswith(home + "/")}
    if len(rels) > MAX_FILES or sum(blobs[p] for p in rels.values()) > MAX_BYTES:
        raise ValueError(f"{skill} is too big to install ({len(rels)} files)")
    real = os.path.realpath(dest)
    for rel in rels:
        full = os.path.realpath(os.path.join(dest, rel))
        if (not rel or rel.startswith(("/", "\\")) or ".." in re.split(r"[\\/]", rel) or ":" in rel
                or os.path.commonpath([full, real]) != real or full == real):
            raise ValueError(f"unsafe path in skill: {rel!r}")
    data = {rel: fetch(RAW + source + "/HEAD/" + urllib.parse.quote(p)) for rel, p in rels.items()}  # all, then write
    if os.path.exists(dest):
        shutil.rmtree(dest)
    for rel, b in data.items():
        full = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b)
    return sorted(rels)
