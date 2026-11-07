"""What each function does, in one sentence: the author's docstring when there is one, else a small model's summary.

Summaries are cached in <project>/.modfence/purposes.json per file, keyed by the file's sha1, so a file is described
again only after it changes. The model gets the module's source in the prompt and no tools, and the default Claude
Code system prompt is replaced by a short one, so a module costs about a cent with Haiku.
"""
import ast, hashlib, json, os, subprocess, sys, threading

from . import analyze, runner

MODEL = "haiku"
BUDGET = 80_000  # characters of source per model call
SYSTEM = ("You describe Python code for a reader who will not read the code. For every name asked, write one plain "
          "English sentence of at most 18 words saying what it does for its caller, not how it does it. Reply with JSON only.")
LOCK = threading.Lock()  # ponytail: one describe at a time per process; per-project locks if that ever queues


def cache_path(root):
    return os.path.join(root, ".modfence", "purposes.json")


def load(root):
    try:
        return json.loads(analyze.read_text(cache_path(root)))
    except (OSError, ValueError):
        return {}


def sha(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def used_by(graph, module_id):
    """{name: [modules that import it with `from ... import name`]} for names defined in module_id."""
    out = {}
    for e in graph["edges"]:
        if e["target"] == module_id:
            for r in e["receipts"]:
                if r.get("name"):
                    out.setdefault(r["name"], set()).add(e["source"])
    return {k: sorted(v) for k, v in out.items()}


def module_view(root, graph, module_id):
    """The module as functions: [{file, name, kind, args, doc, purpose, source, used_by}], plus the module's purpose.
    source is "doc" (the author's docstring), "ai" (a cached summary of the current file) or None (not described)."""
    m = next((x for x in graph["modules"] if x["id"] == module_id), None)
    if not m:
        raise LookupError("no such module")
    cache, users = load(root), used_by(graph, module_id)
    funcs, stale = [], 0
    for f in m["files"]:
        text = analyze.read_text(os.path.join(root, f))
        try:
            units = analyze.functions(ast.parse(text), text.splitlines())
        except SyntaxError:
            continue
        c = cache.get(f, {})
        ai = c.get("names", {}) if c.get("sha") == sha(text) else {}
        for u in units:
            purpose, src = (u["doc"], "doc") if u["doc"] else (ai.get(u["name"]), "ai") if ai.get(u["name"]) else ("", None)
            stale += src is None
            funcs.append(dict(u, file=f, purpose=purpose, source=src, used_by=users.get(u["name"].split(".")[0], [])))
    mp = m["doc"] or cache.get("modules", {}).get(module_id, {}).get("text", "")
    return {"module": module_id, "purpose": mp, "purpose_source": "doc" if m["doc"] else "ai" if mp else None,
            "functions": funcs, "undescribed": stale}


def _ask(claude, prompt):
    """(parsed JSON object, cost in USD) from one tool-less model call."""
    exe = [sys.executable, claude] if claude.endswith(".py") else [claude]
    cmd = exe + ["-p", "--model", MODEL, "--output-format", "json", "--tools", "", "--system-prompt", SYSTEM,
                 "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "project"]  # no user settings (language ...)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"  # the user's CLAUDE.md is not needed to describe code
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=240)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError((p.stderr or p.stdout or f"exit {p.returncode}").strip()[-400:])
    text = res.get("result") or ""
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        raise RuntimeError("the model did not return JSON")
    return obj, res.get("total_cost_usd")


def describe(root, graph, module_id, claude):
    """Summarize the module's functions that have no docstring and no cached summary. Returns cost in USD (None if
    nothing was asked)."""
    if not claude:
        raise RuntimeError("Claude Code CLI not found.")
    with LOCK:
        view, cache = module_view(root, graph, module_id), load(root)
        todo = {}
        for f in view["functions"]:
            if f["source"] is None:
                todo.setdefault(f["file"], []).append(f["name"])
        need_module = not view["purpose"]
        if not todo and not need_module:
            return None
        mod_files = next(x["files"] for x in graph["modules"] if x["id"] == module_id)
        files = sorted(todo) or mod_files  # only the module purpose is missing: show it the whole module
        cost, batch, size, batches = 0.0, [], 0, []
        for f in files:
            text = analyze.read_text(os.path.join(root, f))
            if batch and size + len(text) > BUDGET:
                batches.append(batch)
                batch, size = [], 0
            batch.append((f, text))
            size += len(text)
        batches.append(batch)
        for i, b in enumerate(batches):
            parts = []
            for f, text in b:
                parts.append(f"FILE {f}\nNAMES: {', '.join(todo.get(f, []))}\n```python\n{text}\n```")
            ask_module = need_module and i == 0
            shape = '{"<file>": {"<name>": "<sentence>", ...}, ...' + (', "__module__": "<sentence>"' if ask_module else "") + "}"
            prompt = ("Describe the NAMES listed under each file" + (
                f", and under the key __module__ what the module `{module_id}` as a whole is for" if ask_module else "")
                + f". Reply with exactly this JSON shape: {shape}\n\n" + "\n\n".join(parts))
            obj, c = _ask(claude, prompt)
            cost += c or 0
            for f, text in b:
                got = obj.get(f) if isinstance(obj.get(f), dict) else {}
                entry = cache.get(f) if cache.get(f, {}).get("sha") == sha(text) else {"sha": sha(text), "names": {}}
                entry["names"].update({k: str(v).strip() for k, v in got.items() if k in todo.get(f, []) and v})
                cache[f] = entry
            if ask_module and obj.get("__module__"):
                cache.setdefault("modules", {})[module_id] = {"text": str(obj["__module__"]).strip()}
        runner.state_dir(root)
        runner.write_text(cache_path(root), json.dumps(cache, indent=1, ensure_ascii=False))
        return round(cost, 5)
