"""Run one module-scoped request through the user's own Claude Code CLI and turn its stream into UI events.

Each request runs `claude -p --output-format stream-json` in the project root, with:
- a system note describing the selected modules: their files, what they depend on and what depends on them;
- a PreToolUse hook (scope_guard.py) that denies edits outside those modules;
- `--resume` of that module's previous session, so every module keeps its own conversation.

After the run the project is re-scanned. Files changed outside the scope (for example by a shell command,
which the hook cannot see) are reported as a scope breach. Modules that import hashlib, a changed module are the
ripple of the change.
"""
import difflib, glob, hashlib, itertools, json, os, re, shutil, subprocess, sys, threading, time

from . import analyze, brief

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "scope_guard.py")
SHOW = os.path.join(HERE, "show.py")
DONE_CHECK = os.path.join(HERE, "done_check.py")
PLAN_RULE = (
    "This is the planning step of fence coding. You may read any file but edit nothing; a hook blocks every edit. "
    "Read only what you need. Then reply with one JSON object and nothing else, in this shape:\n"
    '{"questions": [{"q": "...", "options": ["...", "..."], "recommended": 0}], '
    '"plan": {"goal": "one sentence", "functions": [{"file": "path.py", "name": "function or Class.method", '
    '"change": "add|change|remove", "why": "few words"}], "done": "how we will know it works"}}\n'
    "Ask at most 4 questions, only about decisions where different answers lead to different code, each with 2 to 4 "
    "short options and the index of the one you recommend. Ask none when the request is clear. The plan may only "
    "touch files inside the editable modules: {where}. If the request needs more, say so in the goal.")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
ALLOWED_TOOLS = ("Read Glob Grep Edit Write MultiEdit TodoWrite Bash(python:*) Bash(python3:*) Bash(py:*) "
                 "Bash(ls:*) Bash(cat:*) Bash(head:*) Bash(wc:*) Bash(git status:*) Bash(git diff:*) Bash(git log:*)")
_ids = itertools.count(1)


def find_claude():
    """CLAUDE_BIN, else the newest Claude Code binary bundled with the VS Code extension, else `claude` on PATH."""
    if os.environ.get("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    exe = "claude.exe" if os.name == "nt" else "claude"
    pattern = os.path.join(os.path.expanduser("~"), ".vscode", "extensions", "anthropic.claude-code-*",
                           "resources", "native-binary", exe)

    def version(p):
        m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", p)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    bundled = sorted(glob.glob(pattern), key=version)
    return bundled[-1] if bundled else shutil.which("claude")


def state_dir(root):
    d = os.path.join(root, ".modfence")
    os.makedirs(d, exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        write_text(gi, "*\n")
    return d


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_sessions(root):
    p = os.path.join(root, ".modfence", "sessions.json")  # reading never creates .modfence
    try:
        return json.loads(analyze.read_text(p))
    except (OSError, ValueError):
        return {}


def save_session(root, key, session_id):
    s = load_sessions(root)
    s[key] = session_id
    write_text(os.path.join(state_dir(root), "sessions.json"), json.dumps(s, indent=1))


def scope_key(scope):
    return "+".join(sorted(scope))


def history_path(root, scope):
    safe = re.sub(r"[^A-Za-z0-9_.+-]", "_", scope_key(scope)) or "_"
    if len(safe) > 80:  # a role fenced as its files: keep the name short enough for Windows paths
        safe = safe[:40] + "-" + hashlib.sha1(scope_key(scope).encode("utf-8")).hexdigest()[:12]
    return os.path.join(root, ".modfence", "history", safe + ".jsonl")


def load_history(root, scope, limit=20):
    try:
        lines = analyze.read_text(history_path(root, scope)).splitlines()
    except OSError:
        return []
    out = []
    for l in lines[-limit:]:
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def forget(root, scope):
    """Start this scope's conversation over: drop its session id and history."""
    s = load_sessions(root)
    s.pop(scope_key(scope), None)
    write_text(os.path.join(state_dir(root), "sessions.json"), json.dumps(s, indent=1))
    try:
        os.remove(history_path(root, scope))
    except OSError:
        pass


def show_command():
    fwd = lambda p: p.replace("\\", "/")
    return f'"{fwd(sys.executable)}" "{fwd(SHOW)}"'


def context_note(graph, scope, read_only=False, phase=None, sealed=False):
    """System note telling the agent which modules it works on and how they connect to the rest. Sealed (golden
    rule 4): the rest of the project is the brief, not code it may read."""
    mods = {m["id"]: m for m in graph["modules"]}
    out_edges = [e for e in graph["edges"] if e["source"] in scope and e["target"] not in scope]
    in_edges = [e for e in graph["edges"] if e["target"] in scope and e["source"] not in scope]
    where = ", ".join("`(project root files)`" if s == "." else f"function `{s.split('::')[1]}` in `{s.split('::')[0]}`"
                      if "::" in s else f"`{s}`" if s.endswith(".py") else f"`{s}/`" for s in scope)
    if phase == "plan":
        rule = PLAN_RULE.replace("{where}", where)
    elif read_only:
        rule = ("This is a read-only session for learning the code: you may read any file, but you may not create "
                "or edit any file, and a hook blocks every edit. Explain, point to exact file:line locations, and give "
                "hints rather than finished solutions unless the user asks for one.")
    else:
        rule = (("You may read any file in the project, but you" if not sealed else "You") + " may only create or edit files inside: " + where
                + ". A hook blocks edits anywhere else. If the request needs a change in another module, do what you can "
                  "inside the scope, then say exactly which module needs what change, and why.")
    if sealed:
        rule += (" This run is sealed: you can read and search only the fence and the tests; other modules' code is "
                 "hidden so you cannot depend on or break their internals. What they offer, and what the fence must keep "
                 f"working, is in the brief below. For one definition's docstring run: {show_command()} path/to/file.py::name . "
                 "To check behaviour run the tests (python -m pytest path/to/test_file.py -q); python -c, cat and shell "
                 "chaining or redirection are blocked in this run, so do not try them.")
    lines = [f"You are working in modfence on project `{graph['name']}`, focused on module(s): "
             + ", ".join(f"`{s}`" for s in scope) + ".", rule, ""]
    loose = [s for s in scope if s not in mods]
    if loose:  # files and functions fenced one by one (a role, or a function)
        lines.append("Fenced files and functions: " + ", ".join(f"`{s}`" for s in loose[:60]) + (" ..." if len(loose) > 60 else ""))
    for s in scope:
        m = mods.get(s)
        if not m:
            continue
        if sealed and m["kind"] == "tests":  # editable, readable; listing every test file only costs tokens
            lines.append(f"Module `{s}`: the tests ({len(m['files'])} files), inside the fence.")
            continue
        lines.append(f"Module `{s}`" + (f": {m['doc']}" if m["doc"] else ""))
        lines.append("  files: " + ", ".join(f"{f} ({graph['files'][f]['lines']} lines)" for f in m["files"]))
        if m["names"] and not sealed:  # sealed: the brief's contract says what matters
            lines.append("  public names: " + ", ".join(f"{n['name']} ({n['file']}:{n['line']})" for n in m["names"][:40]))
    if sealed:
        lines += [x for x in (brief.LEGEND[brief.DEFAULT], brief.brief(graph, scope)) if x]
    elif out_edges:
        lines.append("Depends on (outside the scope): " + "; ".join(
            f"`{e['target']}` via " + ", ".join(f"{r['file']}:{r['line']}" for r in e["receipts"][:3]) for e in out_edges))
    if in_edges and not sealed:
        lines.append("Used by (outside the scope; changing a public name breaks them): " + "; ".join(
            f"`{e['source']}` via " + ", ".join(f"{r['file']}:{r['line']}" for r in e["receipts"][:3]) for e in in_edges))
    cmd = test_command(graph["root"]) if phase == "build" else None
    if cmd:
        shown = cmd if isinstance(cmd, str) else " ".join(["python"] + cmd[1:])
        lines.append(f"Done check: when you stop, modfence runs the project's tests ({shown}) "
                     "and sends you the output if they fail. Do not run the whole suite yourself, and do not ask the user to.")
        lines.append("Keep the answer short: what you changed, per function, and anything the user must decide.")
    else:
        lines.append("Keep the answer short. When you change code, run the relevant tests if the project has them.")
    return "\n".join(lines)


class Job:
    """phase: None (a plain run), "plan" (read-only, answers with questions and a plan as JSON) or "build" (edits, and
    a Stop hook runs the project's tests before the agent may finish)."""
    def __init__(self, root, scope, prompt, graph, claude_bin, read_only=False, phase=None, seal=True, resume=None):
        self.id = f"r{int(time.time() * 1000)}{next(_ids)}"  # unique across restarts: runs are stored on disk
        self.root, self.scope, self.prompt, self.graph, self.claude = root, list(scope), prompt, graph, claude_bin
        self.phase = phase if phase in ("plan", "build") else None
        self.read_only = bool(read_only) or self.phase == "plan"
        # sealed unless asked not to, or a plain read-only run (Explain), which may read everything to teach
        self.sealed = bool(seal) and not (self.read_only and self.phase != "plan")
        # "file::function" fences the function: the hook allows its file, and _finish flags other functions changed there
        self.editable = [] if self.read_only else sorted({s.split("::")[0] for s in scope})
        self.fn_fence = {}
        for s in scope:
            if "::" in s:
                self.fn_fence.setdefault(s.split("::")[0], set()).add(s.split("::")[1])
        self.events, self.cond, self.done, self.proc = [], threading.Condition(), False, None
        self.started = time.time()
        self.resume = resume  # a session to continue, after the user approved a request to edit outside the fence

    # ----- event log -----
    def emit(self, kind, **data):
        with self.cond:
            self.events.append(dict(data, kind=kind, i=len(self.events), t=round(time.time() - self.started, 2)))
            self.cond.notify_all()

    def wait_events(self, start, timeout=15):
        """Events from index start; blocks until there is something new or the job is done."""
        with self.cond:
            if start >= len(self.events) and not self.done:
                self.cond.wait(timeout)
            return self.events[start:], self.done

    # ----- run -----
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def cancel(self):
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True)
            else:
                self.proc.terminate()
            self.emit("status", text="Cancelled.")

    def system_note(self):
        return context_note(self.graph, self.scope, self.read_only, self.phase, self.sealed)

    def _settings_file(self):
        p = os.path.join(state_dir(self.root), f"settings-{self.id}.json")
        fwd = lambda p: p.replace("\\", "/")  # hook commands run in a POSIX shell, also on Windows
        cmd = f'"{fwd(sys.executable)}" "{fwd(GUARD)}"'
        hooks = {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit" + ("|Read|Grep|Bash" if self.sealed else ""),
                                 "hooks": [{"type": "command", "command": cmd, "timeout": 10, "onFailure": "block"}]}]}
        if self.phase == "build" and test_command(self.root):
            hooks["Stop"] = [{"hooks": [{"type": "command", "command": f'"{fwd(sys.executable)}" "{fwd(DONE_CHECK)}"',
                                         "timeout": 300}]}]
        write_text(p, json.dumps({"hooks": hooks}))
        return p

    def _run(self):
        settings = None
        before = analyze.snapshot(self.root)
        self.before_bytes = analyze.snapshot_bytes(self.root)
        for p in before:  # the fence's own files stay revertible in a project too big for the byte budget
            if p not in self.before_bytes and _in_scope(p, self.editable):
                self.before_bytes[p] = _read_or_none(os.path.join(self.root, p))
        try:
            if not self.claude or not os.path.exists(self.claude) and not shutil.which(self.claude):
                raise RuntimeError("Claude Code CLI not found. Install it, log in, or set CLAUDE_BIN.")
            settings = self._settings_file()
            key = scope_key(self.scope)
            session = self.resume or load_sessions(self.root).get(key)
            exe = [sys.executable, self.claude] if self.claude.endswith(".py") else [self.claude]  # .py: a test double
            cmd = exe + ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                   "--permission-mode", "acceptEdits", "--allowedTools", ALLOWED_TOOLS, "--settings", settings]
            note = self.system_note()
            if note:
                cmd += ["--append-system-prompt", note]
            if session:
                cmd += ["--resume", session]
            env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
            env.update(MODFENCE_ROOT=self.root, MODFENCE_SCOPE=os.pathsep.join(self.editable), MODFENCE_RUN=self.id)
            if self.sealed:
                env.update(MODFENCE_SEAL="1", MODFENCE_FENCE=os.pathsep.join(sorted({s.split("::")[0] for s in self.scope})))
            mode = "planning, read-only" if self.phase == "plan" else "read-only" if self.read_only else "can edit " + ", ".join(self.editable)
            mode += ", sealed" if self.sealed else ""
            self.emit("status", text=("Resumed this scope's session" if session else "New session") + f" ({mode}).")
            self.proc = subprocess.Popen(cmd, cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
            stderr = []
            reader = threading.Thread(target=lambda: stderr.extend(self.proc.stderr), daemon=True)
            reader.start()
            self._consume(self.proc.stdout, key)
            self.proc.wait()
            reader.join(5)
            self.proc.stdout.close()
            self.proc.stderr.close()
            if self.proc.returncode not in (0, None) and not any(e["kind"] == "result" for e in self.events):
                self.emit("error", text=("".join(stderr)[-800:] or f"claude exited with code {self.proc.returncode}").strip())
        except Exception as e:
            self.emit("error", text=f"{type(e).__name__}: {e}")
        finally:
            if settings and os.path.exists(settings):
                os.remove(settings)
            self._finish(before)

    def _consume(self, stream, key):
        tools = {}  # tool_use_id -> name
        for line in stream:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "system" and ev.get("subtype") == "init" and ev.get("session_id"):
                save_session(self.root, key, ev["session_id"])
                self.model = ev.get("model")
            elif t == "stream_event":
                se = ev.get("event") or {}
                d = se.get("delta") or {}
                if (se.get("type") == "content_block_delta" and d.get("type") == "text_delta" and not ev.get("parent_tool_use_id")
                        and self.phase != "plan"):  # a plan streams as JSON: shown as a card when it is complete
                    self.emit("text", text=d.get("text", ""))
            elif t == "assistant":
                if ev.get("parent_tool_use_id"):
                    continue  # a subagent's inner steps
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        tools[block.get("id")] = block.get("name")
                        self.emit("tool", id=block.get("id"), name=block.get("name"), detail=_tool_detail(block),
                                  edit=block.get("name") in EDIT_TOOLS)
                    elif block.get("type") == "text" and self.phase != "plan":
                        self.emit("text_end")
            elif t == "user":
                for block in (ev.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content")
                        text = content if isinstance(content, str) else " ".join(
                            c.get("text", "") for c in content or [] if isinstance(c, dict))
                        denied = "modfence scope:" in text or "modfence seal:" in text
                        self.emit("tool_result", id=block.get("tool_use_id"), name=tools.get(block.get("tool_use_id")),
                                  error=bool(block.get("is_error")) or denied, denied=denied, text=text[:600])
            elif t == "result":
                if ev.get("session_id"):
                    save_session(self.root, key, ev["session_id"])
                if self.phase == "plan" and not ev.get("is_error"):
                    plan = parse_plan(ev.get("result") or "")
                    self.emit("plan", plan=plan) if plan else self.emit("text", text=ev.get("result") or "")
                self.emit("result", ok=not ev.get("is_error"), cost_usd=ev.get("total_cost_usd"),
                          duration_s=round((ev.get("duration_ms") or 0) / 1000, 1), turns=ev.get("num_turns"),
                          usage=ev.get("usage"), model=getattr(self, "model", None),
                          text=(ev.get("result") or "")[-4000:] if ev.get("is_error") else "")

    def requests(self):
        """Golden rules 4 and 7: the files the agent needed outside the fence, each with its reason. A blocked edit is a
        request; a line "NEED <path>: <why>" in its answer says why (or asks without trying)."""
        rel = lambda p: os.path.relpath(p, self.root).replace("\\", "/") if os.path.isabs(p) else p.replace("\\", "/").removeprefix("./")
        paths = {e["id"]: e.get("detail") or "" for e in self.events if e["kind"] == "tool"}
        blocked = [rel(paths.get(e.get("id"), "")) for e in self.events
                   if e["kind"] == "tool_result" and e.get("denied") and "modfence scope:" in (e.get("text") or "")]
        text = "".join(e.get("text") or "" for e in self.events if e["kind"] == "text")
        why = {rel(m.group(1).strip()): m.group(2).strip() for m in re.finditer(r"^[ \t*>-]*NEED\s+`?([^`:\n]+?)`?\s*:\s*(.+)$", text, re.M)}
        seen, out = set(), []
        for p in blocked + list(why):
            if p and p not in seen and not _in_scope(p, self.editable):
                seen.add(p)
                out.append({"path": p, "why": why.get(p, "")})
        return out

    def _finish(self, before):
        try:
            after = analyze.snapshot(self.root)
            added, modified, deleted = analyze.diff(before, after)
            changed = [p for p in added + modified + deleted if not p.startswith(".modfence/")]
            outside = [p for p in changed if not _in_scope(p, self.editable)]
            graph = analyze.analyze(self.root)
            split = set(graph.get("split", ()))
            changed_mods = sorted({analyze.module_of(p, split) for p in changed if p.endswith(".py")})
            ripple = analyze.dependents(graph, changed_mods)
            checks = _read_jsonl(os.path.join(run_dir(self.root, self.id), "checks.jsonl"))
            check = dict(ok=checks[-1]["ok"], summary=checks[-1]["summary"], blocked=sum(c["blocked"] for c in checks)) if checks else None
            res = next((e for e in reversed(self.events) if e["kind"] == "result"), {})
            requests = self.requests()
            if requests:
                self.emit("requests", items=requests)
            # golden rule 3: names other modules used before the run, whose signature the run broke
            contract = brief.contract_breaks(self.graph, {p: (None if p in added else self.before_bytes.get(p),
                                                              None if p in deleted else _read_or_none(os.path.join(self.root, p)))
                                                          for p in modified + deleted if p.endswith(".py")})
            files = save_run(self, changed, set(added), set(deleted), set(outside),
                             dict(prompt=self.prompt, phase=self.phase, modules=changed_mods, ripple=ripple, check=check,
                                  cost_usd=res.get("cost_usd"), turns=res.get("turns"), contract=contract, requests=requests))
            out_fns = [f"{f['path']}::{u['name']}" for f in files if f["path"] in self.fn_fence for u in f["funcs"] or []
                       if u["name"] != "(module level)" and not any(u["name"] == n or u["name"].startswith(n + ".")
                                                                   for n in self.fn_fence[f["path"]])]
            if check:
                self.emit("check", **check)
            self.emit("changes", added=added, modified=modified, deleted=deleted, outside_scope=outside, outside_functions=out_fns,
                      modules=changed_mods, ripple=ripple, run=self.id, files=files, contract=contract)
        except Exception as e:
            self.emit("error", text=f"rescan failed: {e}")
        with self.cond:
            done = dict(kind="done", i=len(self.events), t=round(time.time() - self.started, 2))
            # History is written before "done" goes out, so a client that reloads on "done" sees this run.
            try:  # keep the runs per scope, so reopening a module shows them
                os.makedirs(os.path.join(state_dir(self.root), "history"), exist_ok=True)
                with open(history_path(self.root, self.scope), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"job": self.id, "prompt": self.prompt, "scope": self.scope, "at": self.started,
                                        "read_only": self.read_only, "phase": self.phase, "events": self.events + [done]},
                                       ensure_ascii=False) + "\n")
            except OSError:
                pass
            self.done = True
            self.events.append(done)
            self.cond.notify_all()


# ---------- runs on disk: diff and revert ----------
RUN_ID = re.compile(r"^[A-Za-z0-9]{1,40}$")


def run_dir(root, run_id):
    if not RUN_ID.match(run_id or ""):
        raise LookupError("bad run id")
    return os.path.join(root, ".modfence", "runs", run_id)


def _read_or_none(path):
    try:
        return analyze.read_bytes(path)
    except OSError:
        return None


def _stat(before, after):
    """(plus, minus) changed lines, or (None, None) for binary content."""
    try:
        a = (before or b"").decode("utf-8").splitlines()
        b = (after or b"").decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None, None
    plus = minus = 0
    for line in difflib.unified_diff(a, b, lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            plus += 1
        elif line.startswith("-") and not line.startswith("---"):
            minus += 1
    return plus, minus


def save_run(job, changed, added, deleted, outside, extra=None):
    """Store the before and after bytes of every changed file, so the run can be shown as a diff and reverted."""
    d = run_dir(job.root, job.id)
    files = []
    for p in changed:
        before = None if p in added else job.before_bytes.get(p)
        after = None if p in deleted else _read_or_none(os.path.join(job.root, p))
        revertible = p in added or before is not None
        for kind, data in (("before", before), ("after", after)):
            if data is not None:
                target = os.path.join(d, kind, p)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
        plus, minus = _stat(before, after)
        status = "added" if p in added else "deleted" if p in deleted else "modified"
        funcs = analyze.function_changes(before, after) if p.endswith(".py") else None
        files.append({"path": p, "status": status, "plus": plus, "minus": minus, "outside": p in outside,
                      "revertible": revertible, "funcs": funcs})
    os.makedirs(d, exist_ok=True)
    write_text(os.path.join(d, "run.json"), json.dumps(dict(extra or {}, run=job.id, scope=job.scope, editable=job.editable,
                                                            at=job.started, files=files), indent=1, ensure_ascii=False))
    return files


def versions(root):
    """Every stored run that changed files, oldest first: the project's version history."""
    d = os.path.join(root, ".modfence", "runs")
    out = []
    for name in os.listdir(d) if os.path.isdir(d) else ():
        try:
            run = load_run(root, name)
        except LookupError:
            continue
        if run.get("files"):
            out.append(run)
    return sorted(out, key=lambda r: r.get("at") or 0)


def load_run(root, run_id):
    p = os.path.join(run_dir(root, run_id), "run.json")
    try:
        return json.loads(analyze.read_text(p))
    except (OSError, ValueError):
        raise LookupError("no such run")


def run_diff(root, run_id, path):
    """Unified diff of one file as the run changed it."""
    run = load_run(root, run_id)
    if path not in {f["path"] for f in run["files"]}:
        raise LookupError("file not in this run")
    d = run_dir(root, run_id)
    before = _read_or_none(os.path.join(d, "before", path))
    after = _read_or_none(os.path.join(d, "after", path))
    try:
        a = (before or b"").decode("utf-8").splitlines()
        b = (after or b"").decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return "(binary file)"
    return "\n".join(difflib.unified_diff(a, b, "a/" + path, "b/" + path, lineterm="", n=3)) or "(no textual change)"


def revert_run(root, run_id, paths=None):
    """Put the files a run changed back the way they were. A file edited again after the run is left alone."""
    run, d = load_run(root, run_id), run_dir(root, run_id)
    reverted, skipped = [], []
    for f in run["files"]:
        p = f["path"]
        if paths and p not in paths:
            continue
        full = os.path.join(root, p)
        after = _read_or_none(os.path.join(d, "after", p))
        if _read_or_none(full) != after:
            skipped.append({"path": p, "why": "changed again after this run"})
            continue
        if not f["revertible"]:
            skipped.append({"path": p, "why": "its old content was not captured"})
            continue
        if f["status"] == "added":
            os.remove(full)
        else:
            os.makedirs(os.path.dirname(full) or root, exist_ok=True)
            with open(full, "wb") as out:
                out.write(analyze.read_bytes(os.path.join(d, "before", p)))
        reverted.append(p)
    if reverted:  # History shows the version as reverted
        run["reverted"] = sorted(set(run.get("reverted", [])) | set(reverted))
        write_text(os.path.join(d, "run.json"), json.dumps(run, indent=1, ensure_ascii=False))
    return reverted, skipped


def _read_jsonl(path):
    try:
        return [json.loads(l) for l in analyze.read_text(path).splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def parse_plan(text):
    """The plan object from a planning reply (JSON, possibly inside a code fence), or None."""
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("plan"), dict):
        return None
    qs = [q for q in obj.get("questions") or [] if isinstance(q, dict) and q.get("q") and isinstance(q.get("options"), list)]
    return {"questions": qs[:4], "plan": obj["plan"]}


def _in_scope(path, scope):
    for s in scope:
        if s in (".", ""):
            if "/" not in path:
                return True
        elif path == s or path.startswith(s.strip("/") + "/"):
            return True
    return False


def _tool_detail(block):
    ti = block.get("input") or {}
    for k in ("file_path", "notebook_path", "pattern", "command", "path", "description"):
        if ti.get(k):
            return str(ti[k])[:160]
    if block.get("name") == "TodoWrite":
        return f"{len(ti.get('todos') or [])} items"
    return ""


PYTEST_MARKERS = (("pytest.ini", ""), ("conftest.py", ""), ("pyproject.toml", "[tool.pytest"), ("setup.cfg", "[tool:pytest]"),
                  ("tox.ini", "[pytest]"))


def project_python(root):
    """The project's own virtualenv Python (.venv, venv or env), else the Python running modfence."""
    for d in (".venv", "venv", "env"):
        for exe in ("Scripts/python.exe", "bin/python"):
            if os.path.isfile(os.path.join(root, d, exe)):
                return os.path.join(root, d, exe)
    return sys.executable


def test_command(root):
    """How to run the project's tests, or None if it has none: MODFENCE_TEST_CMD (a shell command) if set; pytest
    when the project is configured for it; else unittest discover on tests/ or test/."""
    if os.environ.get("MODFENCE_TEST_CMD"):
        return os.environ["MODFENCE_TEST_CMD"]
    py = project_python(root)
    for name, marker in PYTEST_MARKERS:
        try:
            if marker in analyze.read_text(os.path.join(root, name)):
                return [py, "-m", "pytest", "-q", "-x"]
        except OSError:
            pass
    for d in ("tests", "test"):
        if os.path.isdir(os.path.join(root, d)):
            return [py, "-m", "unittest", "discover", "-s", d, "-t", "."]
    return None


def run_tests(root, timeout=270):
    """Run the project's tests. Returns (ok, summary line, tail of output); ok is None when nothing could be
    checked (no tests, no pytest, too slow), so the done check never blocks on that."""
    cmd = test_command(root)
    if not cmd:
        return None, "No tests found (tests/, test/ or a pytest config).", ""
    try:
        p = subprocess.run(cmd, cwd=root, shell=isinstance(cmd, str), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"The tests did not finish in {timeout} s. Set MODFENCE_TEST_CMD to a faster subset.", ""
    out = (p.stdout + p.stderr).strip()
    if "No module named pytest" in out:
        return None, f"pytest is not installed for {cmd[0]}.", out[-3000:]
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    ran = next((l for l in reversed(lines) if l.startswith("Ran ")), "")
    if ran:  # unittest
        summary = ran + " " + next((l for l in reversed(lines) if l.startswith(("OK", "FAILED"))), "")
    else:  # pytest: "=== 3 passed, 1 failed in 0.4s ===", or any other runner's last line
        summary = (lines[-1] if lines else "").strip("= ")
    return p.returncode == 0, summary.strip(), out[-3000:]
