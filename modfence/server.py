"""modfence's local web server: the graph API, module-scoped runs with live events, and the static UI.

Binds to 127.0.0.1 only. Requests must carry a localhost Host header, and state-changing requests must come
from the page itself (X-Modfence header), so another website cannot drive your Claude Code through it.
"""
import atexit, json, os, subprocess, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import analyze, purpose, roles, runner, scope_guard

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


class App:
    def __init__(self, projects, claude_bin=None):
        self.projects = [os.path.abspath(p) for p in projects]
        self.claude = claude_bin or runner.find_claude()
        self.jobs, self.active, self.lock = {}, {}, threading.Lock()

    def project(self, q):
        i = int((q.get("p") or ["0"])[0])
        if not 0 <= i < len(self.projects):
            raise LookupError("no such project")
        return self.projects[i]


def make_handler(app, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet
            pass

        # ----- helpers -----
        def send_json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def guard(self, write=False):
            if self.headers.get("Host") not in allowed_hosts:
                self.send_json({"error": "bad host"}, 403)
                return False
            if write and self.headers.get("X-Modfence") != "1":
                self.send_json({"error": "missing X-Modfence header"}, 403)
                return False
            return True

        # ----- GET -----
        def do_GET(self):
            if not self.guard():
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == "/api/projects":
                    return self.send_json({"projects": [{"i": i, "name": os.path.basename(p), "path": p}
                                                        for i, p in enumerate(app.projects)],
                                           "claude": app.claude or None})
                if u.path == "/api/graph":
                    root = app.project(q)
                    g = analyze.analyze(root)
                    # ponytail: module summaries are not keyed by content; they are refreshed when the module is described again
                    g["ai_purposes"] = {k: v.get("text", "") for k, v in purpose.load(root).get("modules", {}).items()}
                    return self.send_json(g)
                if u.path == "/api/roles":
                    root = app.project(q)
                    return self.send_json(roles.view(root, analyze.analyze(root)))
                if u.path == "/api/versions":
                    return self.send_json({"versions": runner.versions(app.project(q))})
                if u.path == "/api/module":
                    root = app.project(q)
                    return self.send_json(purpose.module_view(root, analyze.analyze(root), (q.get("m") or [""])[0]))
                if u.path == "/api/file":
                    return self.file(app.project(q), (q.get("path") or [""])[0])
                if u.path == "/api/history":
                    scope = [s for s in (q.get("scope") or [""])[0].split("+") if s]
                    return self.send_json({"runs": runner.load_history(app.project(q), scope)})
                if u.path == "/api/diff":
                    return self.send_json({"diff": runner.run_diff(app.project(q), (q.get("run") or [""])[0],
                                                                   (q.get("path") or [""])[0])})
                if u.path == "/api/events":
                    return self.events((q.get("job") or [""])[0], int((q.get("from") or ["0"])[0]))
                return self.static(u.path)
            except LookupError as e:
                return self.send_json({"error": str(e)}, 404)
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

        def static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(WEB, rel))
            if os.path.commonpath([full, os.path.realpath(WEB)]) != os.path.realpath(WEB) or not os.path.isfile(full):
                return self.send_json({"error": "not found"}, 404)
            data = analyze.read_bytes(full)
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def file(self, root, rel):
            full = os.path.realpath(os.path.join(root, rel))
            if os.path.commonpath([full, os.path.realpath(root)]) != os.path.realpath(root) or not os.path.isfile(full):
                return self.send_json({"error": "not found"}, 404)
            return self.send_json({"path": rel, "text": analyze.read_text(full)})

        def events(self, job_id, start):
            job = app.jobs.get(job_id)
            if not job:
                return self.send_json({"error": "no such job"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                i = start
                while True:
                    evs, done = job.wait_events(i)
                    for ev in evs:
                        self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                    i += len(evs)
                    if not evs:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    if done and i >= len(job.events):
                        return
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        # ----- POST -----
        def do_POST(self):
            if not self.guard(write=True):
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                b = self.body()
                if u.path == "/api/ask":
                    return self.ask(app.project(q), b)
                if u.path == "/api/cancel":
                    job = app.jobs.get(b.get("job"))
                    if job:
                        job.cancel()
                    return self.send_json({"ok": bool(job)})
                if u.path.startswith("/api/roles/"):
                    return self.roles(app.project(q), u.path.rsplit("/", 1)[1], b)
                if u.path == "/api/tests":
                    ok, summary, out = runner.run_tests(app.project(q))
                    return self.send_json({"ok": ok, "summary": summary, "output": out})
                if u.path == "/api/revert":
                    with app.lock:
                        running = app.active.get(app.project(q))
                        if running and not running.done:
                            return self.send_json({"error": "wait for the current run to finish"}, 409)
                    reverted, skipped = runner.revert_run(app.project(q), b.get("run") or "", b.get("paths") or None)
                    scope_guard.disarm(app.project(q))  # the run was discarded
                    return self.send_json({"reverted": reverted, "skipped": skipped})
                if u.path == "/api/fence/clear":
                    with app.lock:
                        running = app.active.get(app.project(q))
                        if running and not running.done:  # stays set: changing settings now would show as a run change
                            return self.send_json({"error": "wait for the current run to finish"}, 409)
                    scope_guard.disarm(app.project(q))
                    return self.send_json({"ok": True})
                if u.path == "/api/describe":
                    root, m = app.project(q), b.get("module") or ""
                    graph = analyze.analyze(root)
                    try:
                        cost = purpose.describe(root, graph, m, app.claude)
                    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                        return self.send_json(dict(purpose.module_view(root, graph, m), error=str(e)))
                    return self.send_json(dict(purpose.module_view(root, graph, m), cost_usd=cost))
                if u.path == "/api/forget":
                    runner.forget(app.project(q), [s for s in b.get("scope") or [] if s])
                    return self.send_json({"ok": True})
                return self.send_json({"error": "not found"}, 404)
            except LookupError as e:
                return self.send_json({"error": str(e)}, 404)
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

        def roles(self, root, action, b):
            graph = analyze.analyze(root)
            try:
                if action == "propose":
                    with app.lock:  # ponytail: one proposal at a time across projects
                        roles.propose_and_store(root, graph, app.claude)
                elif action == "rename":
                    roles.rename(root, b.get("id"), b.get("name"))
                elif action == "move":
                    if b.get("path") not in graph["files"]:
                        raise LookupError("no such file")
                    roles.move(root, b.get("path"), b.get("id"))
                elif action == "add":
                    roles.add_role(root, b.get("name"), b.get("purpose", ""))
                elif action == "confirm":
                    roles.confirm(root)
                else:
                    raise LookupError("no such action")
            except ValueError as e:  # a name that cannot be used: say why, change nothing
                return self.send_json({"error": str(e)}, 400)
            return self.send_json(roles.view(root, graph))

        def ask(self, root, b):
            prompt = (b.get("prompt") or "").strip()
            scope = [s for s in b.get("scope") or [] if isinstance(s, str) and s]
            graph = analyze.analyze(root)
            # a scope entry is a module, a file (a role is fenced as its files) or "file::function"
            known = {m["id"] for m in graph["modules"]} | set(graph["files"])
            if not prompt or not scope or not {s.split("::")[0] for s in scope} <= known:
                return self.send_json({"error": "need a prompt and a scope of known modules"}, 400)
            with app.lock:
                running = app.active.get(root)
                if running and not running.done:
                    return self.send_json({"error": "a run is already in progress in this project", "job": running.id}, 409)
                job = runner.Job(root, scope, prompt, graph, app.claude, read_only=bool(b.get("read_only")), phase=b.get("phase"),
                                 seal=not b.get("unsealed"))
                app.jobs[job.id] = job
                app.active[root] = job
            if not job.read_only or job.phase == "plan":  # Explain fences nothing
                try:  # also fence agents the user starts by hand, until the fence is cleared (before start: not a run change)
                    scope_guard.arm(root, job.scope, job.sealed, ", ".join(job.scope))
                except (OSError, ValueError) as e:
                    job.emit("status", text=f"The fence is not set for other agents: {e}")
            job.start()
            return self.send_json({"job": job.id})

    return H


def serve(projects, port=8765, claude_bin=None, open_browser=True):
    app = App(projects, claude_bin)
    atexit.register(lambda: [scope_guard.disarm(p) for p in app.projects])  # no fence outlives the server
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"modfence: {url}")
    for i, p in enumerate(app.projects):
        print(f"  [{i}] {p}")
    print(f"  claude: {app.claude or 'NOT FOUND (set CLAUDE_BIN)'}")
    def warm():  # parse and hash every project once, so the first graph and the first run start fast
        for p in app.projects:
            analyze.analyze(p)
            analyze.snapshot(p)
    threading.Thread(target=warm, daemon=True).start()
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return app
