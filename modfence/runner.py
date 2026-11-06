"""Run one module-scoped request through the user's own Claude Code CLI and turn its stream into UI events.

Each request runs `claude -p --output-format stream-json` in the project root, with:
- a system note describing the selected modules: their files, what they depend on and what depends on them;
- a PreToolUse hook (scope_guard.py) that denies edits outside those modules;
- `--resume` of that module's previous session, so every module keeps its own conversation.

After the run the project is re-scanned. Files changed outside the scope (for example by a shell command,
which the hook cannot see) are reported as a scope breach. Modules that import a changed module are the
ripple of the change.
"""
import difflib, glob, itertools, json, os, re, shutil, subprocess, sys, threading, time

from . import analyze

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "scope_guard.py")
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


def context_note(graph, scope, read_only=False):
    """System note telling the agent which modules it works on and how they connect to the rest."""
    mods = {m["id"]: m for m in graph["modules"]}
    out_edges = [e for e in graph["edges"] if e["source"] in scope and e["target"] not in scope]
    in_edges = [e for e in graph["edges"] if e["target"] in scope and e["source"] not in scope]
    where = ", ".join(f"`{s}/`" if s != "." else "`(project root files)`" for s in scope)
    if read_only:
        rule = ("This is a read-only session for learning the code: you may read any file, but you may not create "
                "or edit any file, and a hook blocks every edit. Explain, point to exact file:line locations, and give "
                "hints rather than finished solutions unless the user asks for one.")
    else:
        rule = ("You may read any file in the project, but you may only create or edit files inside: " + where
                + ". A hook blocks edits anywhere else. If the request needs a change in another module, do what you can "
                  "inside the scope, then say exactly which module needs what change, and why.")
    lines = [f"You are working in modfence on project `{graph['name']}`, focused on module(s): "
             + ", ".join(f"`{s}`" for s in scope) + ".", rule, ""]
    for s in scope:
        m = mods.get(s)
        if not m:
            continue
        lines.append(f"Module `{s}`" + (f": {m['doc']}" if m["doc"] else ""))
        lines.append("  files: " + ", ".join(f"{f} ({graph['files'][f]['lines']} lines)" for f in m["files"]))
        if m["names"]:
            lines.append("  public names: " + ", ".join(f"{n['name']} ({n['file']}:{n['line']})" for n in m["names"][:40]))
    if out_edges:
        lines.append("Depends on (outside the scope): " + "; ".join(
            f"`{e['target']}` via " + ", ".join(f"{r['file']}:{r['line']}" for r in e["receipts"][:3]) for e in out_edges))
    if in_edges:
        lines.append("Used by (outside the scope; changing a public name breaks them): " + "; ".join(
            f"`{e['source']}` via " + ", ".join(f"{r['file']}:{r['line']}" for r in e["receipts"][:3]) for e in in_edges))
    lines.append("Keep the answer short. When you change code, run the relevant tests if the project has them.")
    return "\n".join(lines)


class Job:
    def __init__(self, root, scope, prompt, graph, claude_bin, read_only=False):
        self.id = f"r{int(time.time() * 1000)}{next(_ids)}"  # unique across restarts: runs are stored on disk
        self.root, self.scope, self.prompt, self.graph, self.claude = root, list(scope), prompt, graph, claude_bin
        self.read_only = bool(read_only)
        self.editable = [] if self.read_only else list(scope)
        self.events, self.cond, self.done, self.proc = [], threading.Condition(), False, None
        self.started = time.time()

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

    def _settings_file(self):
        p = os.path.join(state_dir(self.root), f"settings-{self.id}.json")
        fwd = lambda p: p.replace("\\", "/")  # hook commands run in a POSIX shell, also on Windows
        cmd = f'"{fwd(sys.executable)}" "{fwd(GUARD)}"'
        write_text(p, json.dumps({"hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                                                          "hooks": [{"type": "command", "command": cmd, "timeout": 10, "onFailure": "block"}]}]}}))
        return p

    def _run(self):
        settings = None
        before = analyze.snapshot(self.root)
        self.before_bytes = analyze.snapshot_bytes(self.root)
        try:
            if not self.claude or not os.path.exists(self.claude) and not shutil.which(self.claude):
                raise RuntimeError("Claude Code CLI not found. Install it, log in, or set CLAUDE_BIN.")
            settings = self._settings_file()
            key = scope_key(self.scope)
            session = load_sessions(self.root).get(key)
            exe = [sys.executable, self.claude] if self.claude.endswith(".py") else [self.claude]  # .py: a test double
            cmd = exe + ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                   "--permission-mode", "acceptEdits", "--allowedTools", ALLOWED_TOOLS, "--settings", settings,
                   "--append-system-prompt", context_note(self.graph, self.scope, self.read_only)]
            if session:
                cmd += ["--resume", session]
            env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
            env.update(MODFENCE_ROOT=self.root, MODFENCE_SCOPE=os.pathsep.join(self.editable))
            mode = "read-only" if self.read_only else "can edit " + ", ".join(self.editable)
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
            elif t == "stream_event":
                se = ev.get("event") or {}
                d = se.get("delta") or {}
                if se.get("type") == "content_block_delta" and d.get("type") == "text_delta" and not ev.get("parent_tool_use_id"):
                    self.emit("text", text=d.get("text", ""))
            elif t == "assistant":
                if ev.get("parent_tool_use_id"):
                    continue  # a subagent's inner steps
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        tools[block.get("id")] = block.get("name")
                        self.emit("tool", id=block.get("id"), name=block.get("name"), detail=_tool_detail(block),
                                  edit=block.get("name") in EDIT_TOOLS)
                    elif block.get("type") == "text":
                        self.emit("text_end")
            elif t == "user":
                for block in (ev.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content")
                        text = content if isinstance(content, str) else " ".join(
                            c.get("text", "") for c in content or [] if isinstance(c, dict))
                        denied = "modfence scope:" in text
                        self.emit("tool_result", id=block.get("tool_use_id"), name=tools.get(block.get("tool_use_id")),
                                  error=bool(block.get("is_error")) or denied, denied=denied, text=text[:600])
            elif t == "result":
                if ev.get("session_id"):
                    save_session(self.root, key, ev["session_id"])
                self.emit("result", ok=not ev.get("is_error"), cost_usd=ev.get("total_cost_usd"),
                          duration_s=round((ev.get("duration_ms") or 0) / 1000, 1), turns=ev.get("num_turns"),
                          text=(ev.get("result") or "")[-4000:] if ev.get("is_error") else "")

    def _finish(self, before):
        try:
            after = analyze.snapshot(self.root)
            added, modified, deleted = analyze.diff(before, after)
            changed = [p for p in added + modified + deleted if not p.startswith(".modfence/")]
            outside = [p for p in changed if not _in_scope(p, self.editable)]
            graph = analyze.analyze(self.root)
            changed_mods = sorted({analyze.module_of(p) for p in changed if p.endswith(".py")})
            ripple = analyze.dependents(graph, changed_mods)
            files = save_run(self, changed, set(added), set(deleted), set(outside))
            self.emit("changes", added=added, modified=modified, deleted=deleted, outside_scope=outside,
                      modules=changed_mods, ripple=ripple, run=self.id, files=files)
        except Exception as e:
            self.emit("error", text=f"rescan failed: {e}")
        with self.cond:
            done = dict(kind="done", i=len(self.events), t=round(time.time() - self.started, 2))
            # History is written before "done" goes out, so a client that reloads on "done" sees this run.
            try:  # keep the runs per scope, so reopening a module shows them
                os.makedirs(os.path.join(state_dir(self.root), "history"), exist_ok=True)
                with open(history_path(self.root, self.scope), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"job": self.id, "prompt": self.prompt, "scope": self.scope, "at": self.started,
                                        "read_only": self.read_only, "events": self.events + [done]},
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


def save_run(job, changed, added, deleted, outside):
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
        files.append({"path": p, "status": status, "plus": plus, "minus": minus, "outside": p in outside,
                      "revertible": revertible})
    os.makedirs(d, exist_ok=True)
    write_text(os.path.join(d, "run.json"), json.dumps({"run": job.id, "scope": job.scope, "editable": job.editable,
                                                        "at": job.started, "files": files}, indent=1))
    return files


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
    return reverted, skipped


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


def run_tests(root, timeout=120):
    """Run the project's unittest suite. Returns (ok, summary line, tail of output)."""
    if not os.path.isdir(os.path.join(root, "tests")):
        return None, "No tests/ folder.", ""
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=root,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = (p.stdout + p.stderr).strip()
    summary = next((l for l in reversed(out.splitlines()) if l.startswith(("OK", "FAILED"))), "")
    ran = next((l for l in reversed(out.splitlines()) if l.startswith("Ran ")), "")
    return p.returncode == 0, f"{ran} {summary}".strip(), out[-3000:]
