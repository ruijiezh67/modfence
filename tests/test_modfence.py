"""Deterministic tests for modfence. No model and no network: Claude Code is replaced by tests/fake_claude.py.

Run from the modfence folder: python -m unittest discover -s tests -t .
"""
import atexit, http.client, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from modfence import analyze, purpose, runner, scope_guard, server  # noqa: E402

FAKE = os.path.join(HERE, "fake_claude.py")
_dirs = []
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in _dirs])  # leave no test dirs behind


def project():
    """app/core (leaf), app/api imports core twice, app/cli imports api with a relative import, tests import api."""
    d = tempfile.mkdtemp(prefix="modfence-test-")
    _dirs.append(d)
    files = {
        "app/__init__.py": '"""The app."""\n',
        "app/core/__init__.py": '"""Core values."""\n',
        "app/core/values.py": '"""Values."""\nLIMIT = 3\n\ndef double(x):\n    return 2 * x\n',
        "app/api/__init__.py": "",
        "app/api/handlers.py": "from app.core.values import double\nimport app.core.values\n\ndef handle(x):\n    return double(x)\n",
        "app/cli/__init__.py": "",
        "app/cli/main.py": "from ..api.handlers import handle\n\nclass Cli:\n    pass\n",
        "app/broken/__init__.py": "",
        "app/broken/bad.py": "def oops(:\n",
        "tests/test_api.py": "from app.api.handlers import handle\n",
        "README.md": "not python\n",
    }
    for rel, text in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        write(p, text)
    return d


def write(p, text, mode="w"):
    with open(p, mode, newline="\n") as f:
        f.write(text)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def edge(g, a, b):
    return next((e for e in g["edges"] if e["source"] == a and e["target"] == b), None)


class AnalyzeTest(unittest.TestCase):
    def test_modules_edges_and_receipts(self):
        g = analyze.analyze(project())
        ids = [m["id"] for m in g["modules"]]
        self.assertEqual(ids, ["app", "app/api", "app/broken", "app/cli", "app/core", "tests"])
        e = edge(g, "app/api", "app/core")
        self.assertEqual([(r["file"], r["line"]) for r in e["receipts"]], [("app/api/handlers.py", 1), ("app/api/handlers.py", 2)])
        self.assertEqual(e["receipts"][0]["code"], "from app.core.values import double")
        self.assertIsNotNone(edge(g, "app/cli", "app/api"), "relative import resolved")
        self.assertIsNone(edge(g, "app/core", "app/api"))
        self.assertEqual(next(m for m in g["modules"] if m["id"] == "tests")["kind"], "tests")

    def test_public_names_doc_and_syntax_errors(self):
        g = analyze.analyze(project())
        core = next(m for m in g["modules"] if m["id"] == "app/core")
        self.assertEqual(core["doc"], "Core values.")
        self.assertEqual({n["name"] for n in core["names"]}, {"LIMIT", "double"})
        self.assertIn("SyntaxError", g["files"]["app/broken/bad.py"]["error"])

    def test_ripple_is_transitive(self):
        g = analyze.analyze(project())
        self.assertEqual(analyze.dependents(g, ["app/core"]), ["app/api", "app/cli", "tests"])
        self.assertEqual(analyze.dependents(g, ["app/cli"]), [])

    def test_snapshot_diff(self):
        d = project()
        before = analyze.snapshot(d)
        write(os.path.join(d, "app/core/values.py"), "X = 1\n", "a")
        write(os.path.join(d, "app/core/new.py"), "")
        os.remove(os.path.join(d, "README.md"))
        self.assertEqual(analyze.diff(before, analyze.snapshot(d)), (["app/core/new.py"], ["app/core/values.py"], ["README.md"]))


class FlatProjectTest(unittest.TestCase):
    """Training repos often keep model.py, train.py at the root: each root .py file is its own module."""

    def test_root_files_are_modules_and_fenceable(self):
        d = tempfile.mkdtemp()
        try:
            for name, src in {"model.py": "class GPT: pass\n", "train.py": "from model import GPT\n",
                              "README.md": "x\n"}.items():
                with open(os.path.join(d, name), "w") as f:
                    f.write(src)
            g = analyze.analyze(d)
            self.assertEqual(sorted(m["id"] for m in g["modules"]), ["model.py", "train.py"])
            self.assertEqual([(e["source"], e["target"]) for e in g["edges"]], [("train.py", "model.py")])
            self.assertTrue(scope_guard.allowed("train.py", d, ["train.py"]))
            self.assertFalse(scope_guard.allowed("model.py", d, ["train.py"]))
            self.assertFalse(scope_guard.allowed("README.md", d, ["train.py"]))
        finally:
            shutil.rmtree(d)


class PurposeTest(unittest.TestCase):
    def test_docstrings_first_then_cached_summaries_until_the_file_changes(self):
        d = project()
        write(os.path.join(d, "app/core/values.py"), '"""Values."""\nLIMIT = 3\n\ndef double(x):\n    """Twice x."""\n    return 2 * x\n\ndef half(x):\n    return x / 2\n')
        g = analyze.analyze(d)
        v = purpose.module_view(d, g, "app/core")
        self.assertEqual([(f["name"], f["source"], f["purpose"]) for f in v["functions"]],
                         [("LIMIT", None, ""), ("double", "doc", "Twice x."), ("half", None, "")])
        self.assertEqual(v["functions"][1]["used_by"], ["app/api"], "from app.core.values import double")
        self.assertEqual(v["undescribed"], 2)
        self.assertFalse(os.path.exists(os.path.join(d, ".modfence")), "viewing does not write")
        self.assertEqual(purpose.describe(d, g, "app/core", FAKE), 0.001)
        v = purpose.module_view(d, g, "app/core")
        self.assertEqual((v["functions"][2]["source"], v["functions"][2]["purpose"]), ("ai", "Does half."))
        self.assertIsNone(purpose.describe(d, g, "app/core", FAKE), "cached: no second call")
        write(os.path.join(d, "app/core/values.py"), "\n", "a")
        self.assertIsNone(purpose.module_view(d, g, "app/core")["functions"][2]["source"], "file changed: summary is stale")


class ScopeGuardTest(unittest.TestCase):
    def test_allowed(self):
        d = project()
        self.assertTrue(scope_guard.allowed("app/core/values.py", d, ["app/core"]))
        self.assertTrue(scope_guard.allowed(os.path.join(d, "app", "core", "new.py"), d, ["app/core"]))
        self.assertFalse(scope_guard.allowed("app/api/handlers.py", d, ["app/core"]))
        self.assertFalse(scope_guard.allowed("app/core/../api/handlers.py", d, ["app/core"]))
        self.assertFalse(scope_guard.allowed("../outside.py", d, ["app/core", "."]))
        self.assertFalse(scope_guard.allowed("app/corel/x.py", d, ["app/core"]), "prefix of a name is not inside")
        self.assertTrue(scope_guard.allowed("README.md", d, ["."]))
        self.assertFalse(scope_guard.allowed("app/core/values.py", d, ["."]), "root scope does not include subfolders")

    def hook(self, event, scope, raw=None):
        env = dict(os.environ, MODFENCE_ROOT=self.d, MODFENCE_SCOPE=os.pathsep.join(scope))
        p = subprocess.run([sys.executable, scope_guard.__file__], input=raw if raw is not None else json.dumps(event),
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def test_hook_denies_outside_and_allows_inside_and_reads(self):
        self.d = project()
        out = self.hook({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(self.d, "app/api/handlers.py")}}, ["app/core"])
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("outside the modules you may edit", out["permissionDecisionReason"])
        self.assertIsNone(self.hook({"tool_name": "Write", "tool_input": {"file_path": "app/core/new.py"}}, ["app/core"]))
        self.assertIsNone(self.hook({"tool_name": "Read", "tool_input": {"file_path": "app/api/handlers.py"}}, ["app/core"]))
        self.assertIsNone(self.hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, ["app/core"]))

    def test_hook_fails_closed(self):
        self.d = project()
        self.assertEqual(self.hook(None, ["app/core"], raw="not json")["permissionDecision"], "deny")
        self.assertEqual(self.hook({"tool_name": "Edit", "tool_input": {}}, ["app/core"])["permissionDecision"], "deny")


def run_job(root, scope, prompt):
    job = runner.Job(root, scope, prompt, analyze.analyze(root), FAKE).start()
    deadline = time.time() + 30
    while not job.done and time.time() < deadline:
        time.sleep(0.05)
    assert job.done, "job did not finish"
    return job


class RunnerTest(unittest.TestCase):
    def test_context_note_names_neighbours_with_receipts(self):
        d = project()
        note = runner.context_note(analyze.analyze(d), ["app/core"])
        self.assertIn("`app/core/`", note)
        self.assertIn("Used by", note)
        self.assertIn("app/api/handlers.py:1", note)

    def test_run_streams_events_and_reports_changes(self):
        d = project()
        job = run_job(d, ["app/core"], "please edit app/core/values.py and edit app/api/handlers.py")
        kinds = [e["kind"] for e in job.events]
        for k in ("status", "text", "tool", "tool_result", "result", "changes", "done"):
            self.assertIn(k, kinds)
        self.assertEqual("".join(e["text"] for e in job.events if e["kind"] == "text"), "Looking at the module.")
        ch = next(e for e in job.events if e["kind"] == "changes")
        self.assertEqual(ch["modified"], ["app/api/handlers.py", "app/core/values.py"])
        self.assertEqual(ch["outside_scope"], ["app/api/handlers.py"], "a change the hook could not see is still reported")
        self.assertEqual(ch["modules"], ["app/api", "app/core"])
        self.assertIn("app/cli", ch["ripple"])
        argv = load(os.path.join(d, ".modfence", "fake_argv.json"))
        self.assertIn("--settings", argv["argv"])
        self.assertEqual(argv["scope"], "app/core")
        self.assertFalse([f for f in os.listdir(os.path.join(d, ".modfence")) if f.startswith("settings-")], "settings file removed")

    def test_sessions_resume_history_and_forget(self):
        d = project()
        run_job(d, ["app/core"], "first")
        self.assertEqual(runner.load_sessions(d)["app/core"], "fake-session-1")
        run_job(d, ["app/core"], "second")
        argv = load(os.path.join(d, ".modfence", "fake_argv.json"))["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], "fake-session-1")
        hist = runner.load_history(d, ["app/core"])
        self.assertEqual([h["prompt"] for h in hist], ["first", "second"])
        self.assertEqual(runner.load_history(d, ["app/api"]), [], "each scope has its own conversation")
        runner.forget(d, ["app/core"])
        self.assertNotIn("app/core", runner.load_sessions(d))
        self.assertEqual(runner.load_history(d, ["app/core"]), [])

    def test_run_is_stored_with_diff_and_can_be_reverted(self):
        d = project()
        original = analyze.read_text(os.path.join(d, "app/core/values.py"))
        job = run_job(d, ["app/core"], "edit app/core/values.py and edit app/core/new.py")
        ch = next(e for e in job.events if e["kind"] == "changes")
        files = {f["path"]: f for f in ch["files"]}
        self.assertEqual(files["app/core/values.py"]["status"], "modified")
        self.assertEqual((files["app/core/values.py"]["plus"], files["app/core/values.py"]["minus"]), (1, 0))
        self.assertEqual(files["app/core/new.py"]["status"], "added")
        self.assertIn("+# edited by fake claude", runner.run_diff(d, ch["run"], "app/core/values.py"))
        with self.assertRaises(LookupError):
            runner.run_diff(d, ch["run"], "README.md")
        reverted, skipped = runner.revert_run(d, ch["run"])
        self.assertEqual(sorted(reverted), ["app/core/new.py", "app/core/values.py"])
        self.assertEqual(analyze.read_text(os.path.join(d, "app/core/values.py")), original)
        self.assertFalse(os.path.exists(os.path.join(d, "app/core/new.py")))
        self.assertEqual(runner.revert_run(d, ch["run"])[0], [], "a second revert changes nothing")

    def test_revert_leaves_files_edited_after_the_run(self):
        d = project()
        job = run_job(d, ["app/core"], "edit app/core/values.py")
        run = next(e for e in job.events if e["kind"] == "changes")["run"]
        write(os.path.join(d, "app/core/values.py"), "Y = 2\n", "a")
        reverted, skipped = runner.revert_run(d, run)
        self.assertEqual(reverted, [])
        self.assertEqual(skipped[0]["path"], "app/core/values.py")
        with self.assertRaises(LookupError):
            runner.revert_run(d, "../../etc")

    def test_read_only_run_may_edit_nothing(self):
        d = project()
        job = runner.Job(d, ["app/core"], "edit app/core/values.py", analyze.analyze(d), FAKE, read_only=True).start()
        while not job.done:
            time.sleep(0.05)
        self.assertEqual(load(os.path.join(d, ".modfence", "fake_argv.json"))["scope"], "")
        argv = load(os.path.join(d, ".modfence", "fake_argv.json"))["argv"]
        self.assertIn("read-only session", argv[argv.index("--append-system-prompt") + 1])
        ch = next(e for e in job.events if e["kind"] == "changes")
        self.assertEqual(ch["outside_scope"], ["app/core/values.py"], "any edit in read-only mode is outside the scope")

    def test_changes_are_named_per_function(self):
        d = project()
        job = run_job(d, ["app/core"], "edit app/core/values.py and edit app/core/new.py")
        files = {f["path"]: f for f in next(e for e in job.events if e["kind"] == "changes")["files"]}
        self.assertEqual(files["app/core/values.py"]["funcs"], [{"name": "(module level)", "kind": "code", "status": "changed"}])
        self.assertEqual(files["app/core/new.py"]["funcs"], [], "a new file with only a comment has no functions")
        before = b"X = 1\n\ndef a():\n    return 1\n\nclass K:\n    def m(self):\n        return 1\n"
        after = b"X = 2\n\ndef a():\n    return 2\n\nclass K:\n    def m(self):\n        return 1\n\n    def n(self):\n        pass\n"
        self.assertEqual(analyze.function_changes(before, after), [
            {"name": "K.n", "kind": "method", "status": "added"}, {"name": "X", "kind": "const", "status": "changed"},
            {"name": "a", "kind": "def", "status": "changed"}])
        self.assertIsNone(analyze.function_changes(before, b"def (:"), "unparsable: no function list, not a wrong one")

    def test_plan_phase_reads_only_and_returns_a_plan(self):
        d = project()
        job = runner.Job(d, ["app/core"], "make double faster", analyze.analyze(d), FAKE, phase="plan").start()
        while not job.done:
            time.sleep(0.05)
        self.assertEqual(load(os.path.join(d, ".modfence", "fake_argv.json"))["scope"], "", "planning may edit nothing")
        plan = next(e for e in job.events if e["kind"] == "plan")["plan"]
        self.assertEqual(plan["questions"][0]["recommended"], 0)
        self.assertEqual(plan["plan"]["functions"][0]["name"], "double")
        self.assertFalse([e for e in job.events if e["kind"] == "text"], "the raw JSON is not streamed as text")
        self.assertEqual(runner.load_sessions(d)["app/core"], "fake-plan", "the build resumes the planning session")
        self.assertIsNone(runner.parse_plan("no json here"))

    def test_build_phase_adds_the_done_check_hook(self):
        d = project()
        job = runner.Job(d, ["app/core"], "x", analyze.analyze(d), FAKE, phase="build")
        hooks = load(job._settings_file())["hooks"]
        self.assertIn("done_check.py", hooks["Stop"][0]["hooks"][0]["command"])
        self.assertIn("Do not run the whole suite yourself", job.system_note(), "the agent is told the check runs the tests")
        self.assertNotIn("Stop", load(runner.Job(d, ["app/core"], "x", analyze.analyze(d), FAKE)._settings_file())["hooks"])

    def test_done_check_blocks_once_then_lets_the_agent_stop(self):
        d = project()
        write(os.path.join(d, "tests/test_fail.py"), "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('no')\n")
        env = dict(os.environ, MODFENCE_ROOT=d, MODFENCE_RUN="r1")
        hook = os.path.join(os.path.dirname(HERE), "modfence", "done_check.py")
        first = subprocess.run([sys.executable, hook], input='{"stop_hook_active": false}', capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(first.stdout)["decision"], "block")
        second = subprocess.run([sys.executable, hook], input='{"stop_hook_active": true}', capture_output=True, text=True, env=env)
        self.assertEqual(second.stdout.strip(), "", "a second stop is let through")
        rec = [json.loads(l) for l in open(os.path.join(d, ".modfence/runs/r1/checks.jsonl"))]
        self.assertEqual([(r["ok"], r["blocked"]) for r in rec], [(False, 1), (False, 0)])

    def test_reading_state_creates_nothing(self):
        d = project()
        self.assertEqual(runner.load_history(d, ["app/core"]), [])
        self.assertEqual(runner.load_sessions(d), {})
        self.assertFalse(os.path.exists(os.path.join(d, ".modfence")), "browsing a project must not write to it")

    def test_missing_cli_is_an_error_event(self):
        d = project()
        job = runner.Job(d, ["app/core"], "hi", analyze.analyze(d), os.path.join(d, "no-such-claude")).start()
        while not job.done:
            time.sleep(0.05)
        self.assertTrue(any(e["kind"] == "error" and "not found" in e["text"] for e in job.events))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = project()
        cls.port = 18765
        app = server.App([cls.d], claude_bin=FAKE)
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", cls.port), server.make_handler(app, cls.port))
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read().decode("utf-8")
        c.close()
        return r.status, data

    def test_projects_graph_and_static(self):
        s, data = self.req("GET", "/api/projects")
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(data)["projects"][0]["path"], os.path.abspath(self.d))
        s, data = self.req("GET", "/api/graph?p=0")
        self.assertEqual(len(json.loads(data)["modules"]), 6)
        s, data = self.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn("modfence", data)

    def test_guards(self):
        self.assertEqual(self.req("GET", "/api/projects", headers={"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.req("POST", "/api/tests?p=0", {})[0], 403, "POST needs the X-Modfence header")
        self.assertEqual(self.req("GET", "/api/file?p=0&path=../../etc/passwd")[0], 404)
        self.assertEqual(self.req("GET", "/api/graph?p=7")[0], 404)
        s, data = self.req("POST", "/api/ask?p=0", {"prompt": "x", "scope": ["nope"]}, {"X-Modfence": "1"})
        self.assertEqual(s, 400)

    def test_ask_and_stream_events(self):
        s, data = self.req("POST", "/api/ask?p=0", {"prompt": "edit app/cli/main.py", "scope": ["app/cli"]}, {"X-Modfence": "1"})
        self.assertEqual(s, 200, data)
        job = json.loads(data)["job"]
        s, stream = self.req("GET", f"/api/events?job={job}&from=0")
        events = [json.loads(l[6:]) for l in stream.splitlines() if l.startswith("data: ")]
        self.assertEqual(events[-1]["kind"], "done")
        ch = next(e for e in events if e["kind"] == "changes")
        self.assertEqual(ch["modified"], ["app/cli/main.py"])
        self.assertEqual(ch["outside_scope"], [])
        s, data = self.req("GET", "/api/history?p=0&scope=app/cli")
        self.assertEqual(json.loads(data)["runs"][-1]["prompt"], "edit app/cli/main.py")
        s, data = self.req("GET", f"/api/diff?p=0&run={ch['run']}&path=app/cli/main.py")
        self.assertIn("+# edited by fake claude", json.loads(data)["diff"])
        self.assertEqual(self.req("GET", "/api/diff?p=0&run=../x&path=app/cli/main.py")[0], 404)
        self.assertEqual(self.req("POST", "/api/revert?p=0", {"run": ch["run"]})[0], 403, "needs the X-Modfence header")
        s, data = self.req("POST", "/api/revert?p=0", {"run": ch["run"]}, {"X-Modfence": "1"})
        self.assertEqual(json.loads(data)["reverted"], ["app/cli/main.py"])


if __name__ == "__main__":
    unittest.main()
