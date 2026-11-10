"""Deterministic tests for modfence. No model and no network: Claude Code is replaced by tests/fake_claude.py.

Run from the modfence folder: python -m unittest discover -s tests -t .
"""
from collections import Counter
import atexit, http.client, json, os, re, shutil, subprocess, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from modfence import analyze, brief, purpose, roles, runner, scope_guard, server, skills  # noqa: E402

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

    def test_cached_parse_sees_edits(self):
        d = project()
        self.assertIsNone(edge(analyze.analyze(d), "app/core", "app/cli"))
        write(os.path.join(d, "app/core/values.py"), "from app.cli.main import Cli\n", "a")
        self.assertIsNotNone(edge(analyze.analyze(d), "app/core", "app/cli"), "a changed file is parsed again")
        before = analyze.snapshot(d)
        self.assertIn("app/core/values.py", analyze.snapshot_bytes(d))
        self.assertEqual(analyze.snapshot(d), before, "a warm snapshot matches")


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


class RolesTest(unittest.TestCase):
    def test_a_role_opens_as_a_few_named_parts(self):
        from modfence import roles
        small = ["a/x.py", "a/y.py"]
        self.assertEqual(roles.role_parts(small), {"a/x.py": "x.py", "a/y.py": "y.py"})
        files = [f"ev/{w}_{i}.py" for w in ("round", "study", "watch") for i in range(4)] + [f"ev/misc{i}.py" for i in range(30)]
        parts = roles.role_parts(files)
        self.assertLessEqual(len(set(parts.values())), roles.PART_MAX)
        self.assertEqual({parts[f"ev/round_{i}.py"] for i in range(4)}, {"round"})  # the word as written, not a stem
        self.assertEqual(parts["ev/misc0.py"], "ev/")
        self.assertEqual(parts, roles.role_parts(list(reversed(files))))  # deterministic
        clash = [f"evaluation/x{i}.py" for i in range(9)] + ["backend/evaluation_judge.py", "w/backend/evaluation_judge.py"]
        self.assertEqual(roles.role_parts(clash)["backend/evaluation_judge.py"], "judge", "no part named like a folder")

    def test_entry_points_doors_and_shared_config_are_not_features(self):
        from modfence import roles
        d = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(d)
        for rel, text in {"settings.py": "X = 1\n", "memory.py": "import settings\n", "recorder.py": "import settings\n",
                          "pipeline.py": "import settings, memory\n",
                          "routers/memory_routes.py": "import memory, recorder\n",
                          "app.py": "from routers import memory_routes\n", "main.py": "import app\n"}.items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            write(os.path.join(d, rel), text)
        g = analyze.analyze(d)
        role_of = {"settings.py": "core", "memory.py": "mem", "recorder.py": "rec", "pipeline.py": "pipe",
                   "routers/memory_routes.py": "core", "app.py": "core", "main.py": "core"}
        kind, door_of = roles.kinds(g, role_of)
        self.assertEqual(kind, {"main.py": "entry", "settings.py": "shared", "routers/memory_routes.py": "door"})
        self.assertEqual(door_of, {"routers/memory_routes.py": "mem", "main.py": "core"}, "a door serves the file named like it; an entry, what it imports")
        self.assertEqual(roles.kinds(g, role_of), (kind, door_of))  # deterministic

    def test_areas_hold_every_role_once_in_at_most_seven(self):
        from collections import Counter
        from modfence import roles
        role_of = {f"{r}/f{i}.py": r for r in "abcdefghij" for i in range(3)}
        imports = Counter({frozenset(p): 9 for p in (("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"))})
        groups = roles.suggest_areas(role_of, imports)
        self.assertLessEqual(len(groups), roles.AREA_MAX)
        self.assertEqual(sorted(r for g in groups for r in g), list("abcdefghij"))
        self.assertEqual(groups, roles.suggest_areas(dict(reversed(list(role_of.items()))), imports))  # deterministic
        sizes = [sum(1 for r in role_of.values() if r in g) for g in groups]
        self.assertLessEqual(max(sizes), roles.AREA_CAP * len(role_of) + 3, "no blob")
        together = roles.suggest_areas(role_of, Counter(), [{"a/f0.py", "j/f0.py"}] * 5)
        self.assertTrue(any({"a", "j"} <= set(g) for g in together), "roles that change together share an area")

    def test_runtime_links_find_http_calls_runs_and_copies(self):
        from modfence import roles
        d = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(d)
        body = "".join(f"def step_{i}(x):\n    return x + {i}\n" for i in range(8))
        files = {
            "server/routes.py": "from fastapi import APIRouter\nr = APIRouter(prefix='/v1')\n@r.get('/items/{item_id}')\ndef get(item_id): pass\n",
            "app/client.py": "import urllib.request\ndef fetch(i):\n    return urllib.request.urlopen(f'http://127.0.0.1/v1/items/{i}')\n",
            "tools/run.py": "import subprocess\nsubprocess.run(['python', 'server/routes.py'])\n",
            "server/steps.py": body, "mirror/steps.py": body + "def extra():\n    return 0\n",
            "mirror/routes.py": "from fastapi import APIRouter\nr = APIRouter(prefix='/v1')\n@r.get('/items/{item_id}')\ndef get(item_id): pass\n",
            "mirror/call.py": "URL = '/v1/items/7'\n",
        }
        for rel, text in files.items():
            os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
            write(os.path.join(d, rel), text)
        links = {(l["file"], l["target_file"], l["kind"]) for l in roles.runtime_links(analyze.analyze(d))}
        self.assertIn(("app/client.py", "server/routes.py", "http"), links)  # an f-string path matches a {param} route
        self.assertIn(("tools/run.py", "server/routes.py", "runs"), links)
        self.assertTrue({("mirror/steps.py", "server/steps.py", "copy"), ("server/steps.py", "mirror/steps.py", "copy")} & links)
        self.assertIn(("mirror/call.py", "mirror/routes.py", "http"), links, "a copy calls its own copy's route")
        self.assertNotIn(("mirror/call.py", "server/routes.py", "http"), links)

    def test_blocks_keep_copies_together(self):
        from modfence import roles
        d = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(d)
        body = "".join(f"def watch_{i}(x):\n    return x * {i}\n" for i in range(10))
        for rel, text in {"core/observers/screen.py": body, "win/observers/screen.py": body,
                          "core/memory/store.py": "X = 1\n", "win/ui/page.py": "Y = 2\n"}.items():
            os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
            write(os.path.join(d, rel), text)
        b = roles.blocks(analyze.analyze(d))
        self.assertEqual(b["core/observers/screen.py"], b["win/observers/screen.py"], "a copy is the same job")
        self.assertNotEqual(b["core/memory/store.py"], b["win/ui/page.py"])
        fn, purposes, cost, how = roles.functions(analyze.analyze(d), b, None)  # no model: the deterministic fallback
        self.assertEqual(set(fn), set(b.values()))
        self.assertIsNone(cost)

    def test_project_docs_land_on_the_roles_they_name(self):
        from modfence import docs
        d = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(d)
        for rel, text in {"core/engine.py": "X = 1\n", "ui/window.py": "Y = 2\n", "core/ENGINE.md": "# Engine\nSee engine.py.\n",
                          "README.md": "# App\nRuns ui/window.py.\n"}.items():
            os.makedirs(os.path.join(d, os.path.dirname(rel) or "."), exist_ok=True)
            write(os.path.join(d, rel), text)
        role_of = {"core/engine.py": "r1", "ui/window.py": "r2"}
        v = {x["path"]: x for x in docs.view(d, role_of)["docs"]}
        self.assertEqual(v["core/ENGINE.md"]["boxes"], ["role:r1"], "named by file name and in its folder")
        self.assertEqual(v["README.md"]["boxes"], ["role:r2"], "named by path")
        self.assertIsNone(v["README.md"]["stale"], "no git: stale is N/A, not 0")
        docs.choose(d, "README.md", "role:r2", False)
        docs.choose(d, "README.md", "link:role:r1|role:r2", True)
        v = docs.view(d, role_of)
        self.assertEqual({x["path"]: x["boxes"] for x in v["docs"]}["README.md"], ["link:role:r1|role:r2"])
        self.assertEqual({p for p, *_ in docs.for_fence(d, role_of, ["core/engine.py"])}, {"core/ENGINE.md", "README.md"},
                         "a fence gets its box's docs and the docs on its links")
        docs.add_lesson(d, "core/ENGINE.md", "the cache is per process")
        docs.add_lesson(d, "core/ENGINE.md", "restart after config changes")
        body = open(os.path.join(d, "core/ENGINE.md"), encoding="utf-8").read()
        self.assertEqual(body.count("## Gotchas"), 1)
        self.assertLess(body.index("per process"), body.index("restart after"))
        with self.assertRaises(ValueError):
            docs.safe_doc(d, "../outside.md")

    def test_roles_from_history_keep_what_changes_together(self):
        from modfence import roles
        d = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(d)
        files = [f"{w}/m{i}.py" for w in ("ui", "db", "net", "log") for i in range(3)]
        for f in files:
            os.makedirs(os.path.join(d, os.path.dirname(f)), exist_ok=True)
            write(os.path.join(d, f), "X = 1\n")
        g = analyze.analyze(d)
        together = [{"ui/m0.py", "db/m0.py"}] * 6
        r = roles.by_history(g, most=3, cap=0.6, changes=together)
        self.assertEqual(r["ui/m0.py"], r["db/m0.py"], "folders that change together form one role")
        self.assertLessEqual(len(set(r.values())), 3)
        self.assertEqual(r, roles.by_history(g, most=3, cap=0.6, changes=together))  # deterministic
        self.assertLessEqual(max(list(r.values()).count(v) for v in set(r.values())), 0.6 * len(files) + 3)

    def test_imports_resolve_from_a_subfolder_root(self):
        d = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(d)
        for rel, text in {"backend/kernel/__init__.py": "", "backend/kernel/store.py": "X = 1\n",
                          "backend/observers/screen.py": "from kernel.store import X\n"}.items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            write(os.path.join(d, rel), text)
        self.assertIsNotNone(edge(analyze.analyze(d), "backend/observers", "backend/kernel"),
                             "code run from backend/ imports kernel.store as backend/kernel/store.py")

    def test_words_louvain_and_groupings_are_deterministic(self):
        self.assertEqual({roles.tokens(p)[-1] for p in ("a/segmenter.py", "b/segmentation.py", "c/segment_runner.py")} - {"runn"}, {"segment"})
        w = {(i, j): 1 for g in (range(5), range(5, 10)) for i in g for j in g if i < j}
        w[(4, 5)] = 1
        self.assertEqual(sorted(Counter(roles.louvain(list(range(10)), w).values()).values()), [5, 5])
        g = analyze.analyze(project())
        for name, fn in roles.METHODS.items():
            first = fn(g)
            self.assertEqual(first, fn(g), name)
            self.assertEqual(set(first), set(roles.code_files(g)), name)

    def test_roles_can_be_renamed_and_corrected_without_losing_anything(self):
        d = project()
        g = analyze.analyze(d)
        files = roles.code_files(g)
        roles.save_store(d, roles.to_store({f: "app core" if "/core/" in f else "the_rest:of/it" for f in files}, {}, "test"))
        v = roles.view(d, g)
        self.assertEqual(sorted(r["name"] for r in v["roles"]), ["app core", "the rest of"], "names are tidied to 3 words")
        core = next(r for r in v["roles"] if r["name"] == "app core")
        roles.rename(d, core["id"], "  values   store ")
        for bad in ("", "the rest of", "a b c d", "x" * 25, "a/b"):
            with self.assertRaises(ValueError, msg=bad):
                roles.rename(d, core["id"], bad)
        v = roles.view(d, g)
        renamed = next(r for r in v["roles"] if r["id"] == core["id"])
        self.assertEqual((renamed["name"], renamed["files"]), ("values store", core["files"]), "a rename keeps the files")
        other = next(r for r in v["roles"] if r["id"] != core["id"])
        roles.move(d, "app/cli/main.py", core["id"])
        write(os.path.join(d, "app/core/extra.py"), "def f():\n    return 1\n")
        v = roles.view(d, analyze.analyze(d))
        self.assertIn("app/cli/main.py", next(r for r in v["roles"] if r["id"] == core["id"])["files"])
        self.assertNotIn("app/cli/main.py", next(r for r in v["roles"] if r["id"] == other["id"])["files"])
        self.assertEqual(v["unassigned"], ["app/core/extra.py"], "new files wait to be placed")

    def test_a_function_fence_allows_its_file(self):
        d = project()
        job = runner.Job(d, ["app/core/values.py::double"], "x", analyze.analyze(d), FAKE)
        self.assertEqual((job.editable, job.fn_fence), (["app/core/values.py"], {"app/core/values.py": {"double"}}))
        self.assertIn("function `double` in `app/core/values.py`", job.system_note())


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
        self.assertEqual(p.returncode, 2 if p.stdout.strip() else 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def armed_hook(self, event):
        """Run the hook as an agent started by hand would: no MODFENCE_* variables, the root as its argument."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("MODFENCE_")}
        return subprocess.run([sys.executable, scope_guard.__file__, self.d], input=json.dumps(event),
                              capture_output=True, text=True, env=env)

    def test_arm_and_disarm_keep_the_users_settings(self):
        self.d = project()
        p = os.path.join(self.d, ".claude", "settings.local.json")
        mine = {"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "echo mine"}]}]}}
        os.makedirs(os.path.dirname(p))
        write(p, json.dumps(mine))
        for _ in range(2):  # idempotent
            scope_guard.arm(self.d, ["app/core", "app/core/values.py::double"], True, "core")
        s = load(p)
        self.assertEqual(s["permissions"], mine["permissions"])
        self.assertEqual([e["matcher"] for e in s["hooks"]["PreToolUse"]], ["Bash", "*"], "one modfence entry, after the user's")
        self.assertIn(f'"{self.d.replace(os.sep, "/")}"', s["hooks"]["PreToolUse"][1]["hooks"][0]["command"])
        f = load(os.path.join(self.d, ".modfence", "fence.json"))
        self.assertEqual((f["files"], f["sealed"], f["label"]), (["app/core", "app/core/values.py"], True, "core"))
        self.assertTrue(os.path.exists(os.path.join(self.d, ".modfence", ".gitignore")), "the fence file stays out of git")
        for _ in range(2):
            scope_guard.disarm(self.d)
        self.assertEqual(load(p), mine, "only modfence's hook is removed")
        self.assertFalse(os.path.exists(os.path.join(self.d, ".modfence", "fence.json")))
        fresh = project()
        scope_guard.arm(fresh, ["app/core"], False)
        scope_guard.disarm(fresh)
        self.assertFalse(os.path.exists(os.path.join(fresh, ".claude")), "a settings file modfence made is deleted")

    def test_armed_hook_reads_every_agents_payload_and_denies_outside(self):
        self.d = project()
        out = "app/api/handlers.py"
        self.assertEqual(self.armed_hook({"tool_name": "Edit", "tool_input": {"file_path": out}}).returncode, 0, "no fence: allow")
        scope_guard.arm(self.d, ["app/core"], False)
        patch = f"*** Begin Patch\n*** Update File: app/core/values.py\n@@\n-x\n+y\n*** Update File: {out}\n*** End Patch\n"
        shapes = {"claude": {"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.d, out)}},
                  "cursor": {"tool_name": "Delete", "tool_input": {"file_path": out}},
                  "copilot": {"toolName": "edit", "toolArgs": json.dumps({"path": out})},
                  "codex": {"tool_name": "apply_patch", "tool_input": {"command": patch}},
                  "unknown mutating": {"tool_name": "mcp__fs__move_file", "tool_input": {"source": "app/core/values.py"}}}
        for name, ev in shapes.items():
            p = self.armed_hook(ev)
            self.assertEqual(p.returncode, 2, name)
            got = json.loads(p.stdout)
            self.assertEqual((got["hookSpecificOutput"]["permissionDecision"], got["permissionDecision"], got["decision"]),
                             ("deny", "deny", "block"), name)
            self.assertEqual(got["reason"], got["hookSpecificOutput"]["permissionDecisionReason"])
            self.assertIn("modfence", p.stderr, name)
        for ev in ({"toolName": "create", "toolArgs": json.dumps({"path": "app/core/new.py"})},
                   {"tool_name": "apply_patch", "tool_input": {"command": patch.replace(out, "app/core/new.py")}},
                   {"tool_name": "TodoWrite", "tool_input": {}}, {"tool_name": "Glob", "tool_input": {"pattern": "**"}}):
            p = self.armed_hook(ev)
            self.assertEqual((p.returncode, p.stdout), (0, ""), ev)
        scope_guard.disarm(self.d)
        self.assertEqual(self.armed_hook(shapes["codex"]).returncode, 0, "disarmed: allow")

    def test_apply_patch_paths(self):
        text = ("*** Begin Patch\n*** Add File: a/new.py\n+x\n*** Delete File: b/old.py\n*** Update File: c/m.py\n"
                "*** Move to: d/m.py\n@@\n-x\n+y\n*** End Patch")
        self.assertEqual(scope_guard.patch_paths(text), ["a/new.py", "b/old.py", "c/m.py", "d/m.py"])

    def test_hook_denies_outside_and_allows_inside_and_reads(self):
        self.d = project()
        out = self.hook({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(self.d, "app/api/handlers.py")}}, ["app/core"])
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("outside the modules you may edit", out["permissionDecisionReason"])
        self.assertIsNone(self.hook({"tool_name": "Write", "tool_input": {"file_path": "app/core/new.py"}}, ["app/core"]))
        self.assertIsNone(self.hook({"tool_name": "Read", "tool_input": {"file_path": "app/api/handlers.py"}}, ["app/core"]))
        self.assertIsNone(self.hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, ["app/core"]))

    def test_sealed_run_hides_other_modules_but_gives_their_interface(self):
        self.d = project()
        seal = lambda ev: scope_guard.decide(ev, self.d, ["app/api"], fence=["app/api"])
        read = lambda p: seal({"tool_name": "Read", "tool_input": {"file_path": os.path.join(self.d, p)}})
        out = read("app/core/values.py")
        self.assertIn("modfence seal", out)
        self.assertIn("def double(x)", out, "the denial carries the interface instead of the code")
        self.assertNotIn("return 2 * x", out)
        for ok in ("app/api/handlers.py", "tests/test_api.py", "README.md"):
            self.assertIsNone(read(ok), ok)
        self.assertIsNotNone(seal({"tool_name": "Grep", "tool_input": {"pattern": "x"}}), "a search of the whole project")
        self.assertIsNone(seal({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "app/api"}}))
        bash = lambda c: seal({"tool_name": "Bash", "tool_input": {"command": c}})
        self.assertIsNone(bash("python -m pytest -q"))
        self.assertIsNone(bash(runner.show_command() + " app/core/values.py::double"))
        for bad in ("cat app/core/values.py", "python -m pytest; cat app/core/values.py", "python -c 'print(1)'"):
            self.assertIsNotNone(bash(bad), bad)
        self.assertIsNone(scope_guard.decide({"tool_name": "Read", "tool_input": {"file_path": "app/core/values.py"}}, self.d, ["app/api"]),
                          "unsealed runs read freely")
        shown = subprocess.run([sys.executable, runner.SHOW, "app/core/values.py::double"],
                               capture_output=True, text=True, env=dict(os.environ, MODFENCE_ROOT=self.d))
        self.assertEqual(shown.stdout.strip(), "def double(x)", shown.stderr)

    def test_brief_lists_what_the_fence_uses_and_must_keep(self):
        d = project()
        g = analyze.analyze(d)
        b = brief.brief(g, ["app/api"], "sig")
        self.assertIn("def double(x)", b)
        self.assertIn("handle(x)  <- app/cli, tests", b, "the contract: who relies on the fence")
        self.assertNotIn("return 2 * x", b)
        ids = brief.brief(g, ["app/api"])  # the default, chosen by bench/brief_probe.py
        self.assertIn("double(x)", ids)
        self.assertIn("KEEP handle(x) <M0,M2", ids)
        self.assertIn("M0=app/cli", ids)
        tiny = brief.render_sig(brief.facts(g, ["app/api"]), budget=10)
        self.assertIn("also: double", tiny, "past the budget, names only")
        job = runner.Job(d, ["app/api"], "x", g, FAKE, phase="build")
        self.assertIn("Read|Grep|Bash", load(job._settings_file())["hooks"]["PreToolUse"][0]["matcher"])
        self.assertIn("This run is sealed", job.system_note())
        explain = runner.Job(d, ["app/api"], "x", g, FAKE, read_only=True)
        self.assertFalse(explain.sealed, "Explain reads everything")
        self.assertFalse(runner.Job(d, ["app/api"], "x", g, FAKE, seal=False).sealed)

    def test_contract_breaks_only_for_names_other_modules_use(self):
        d = project()
        g = analyze.analyze(d)
        old = b'"""Values."""\nLIMIT = 3\n\ndef double(x):\n    return 2 * x\n\ndef _helper(a):\n    return a\n'
        case = lambda new: brief.contract_breaks(g, {"app/core/values.py": (old, new)})
        self.assertEqual(case(old.replace(b"return 2 * x", b"return x + x")), [], "a body change keeps the contract")
        self.assertEqual(case(old.replace(b"def _helper(a)", b"def _helper(a, b)")), [], "nobody else uses _helper")
        got = case(old.replace(b"def double(x)", b"def double(x, factor)"))
        self.assertEqual([(b["name"], b["change"]) for b in got], [("double", "new required parameter factor")])
        self.assertEqual(got[0]["users"], ["app/api/handlers.py:1"])
        self.assertEqual(case(old.replace(b"def double(x)", b"def double(x, factor=2)")), [], "an optional parameter is fine")
        self.assertEqual([b["change"] for b in case(old.replace(b"def double(x)", b"def twice(x)"))], ["removed"])
        self.assertEqual([b["change"] for b in case(old.replace(b"def double(x)", b"def double(y)"))], ["parameter x removed", "new required parameter y"])
        self.assertEqual(case(old.replace(b"def double(x):\n    return 2 * x", b"from app.core.other import double")), [], "re-exported")
        # false alarms a replay of requests' history found, now not raised:
        sig = lambda src: brief.signatures(src.encode())
        self.assertEqual(brief.breaks(sig("class D(MutableMapping): pass")["D"], sig("class D(MutableMapping[str, T]): pass")["D"]), [],
                         "a base made generic")
        self.assertEqual(brief.breaks(sig("class J(cookielib.CookieJar): pass")["J"], sig("class J(CookieJar): pass")["J"]), [])
        self.assertEqual(brief.breaks(sig("class S(List[T]): pass")["S"], sig("class S(list[T]): pass")["S"]), [], "typing alias (rich)")
        self.assertEqual(brief.breaks(sig("class J:\n    pass")["J"], sig("class J:\n    _policy: int")["J"]), [],
                         "annotations on a plain class are not constructor parameters")
        self.assertEqual(brief.breaks(sig("@dataclass\nclass P:\n    x: int")["P"], sig("@dataclass\nclass P:\n    x: int\n    y: int")["P"]),
                         ["new required parameter y"], "a dataclass field is")
        self.assertIn("chardet", sig("if TYPE_CHECKING:\n    import chardet\nelse:\n    chardet = None"), "names inside if blocks")
        write(os.path.join(d, "app/cli/extra.py"), "from app.core import values as v\n\ndef go():\n    return v.double(1) + v.LIMIT\n")
        g = analyze.analyze(d)
        got = brief.contract_breaks(g, {"app/core/values.py": (old, old.replace(b"def double(x)", b"def double(x, factor)"))})
        self.assertIn("app/cli/extra.py:4", got[0]["users"], "a use through a module alias (v.double) counts")

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
        self.assertIn(runner.LEAN_RULE, note, "edit runs carry the lean rule (golden rule 1)")
        self.assertNotIn(runner.LEAN_RULE, runner.context_note(analyze.analyze(d), ["app/core"], read_only=True))
        self.assertNotIn(runner.LEAN_RULE, runner.context_note(analyze.analyze(d), ["app/core"], lean=False))

    def test_a_blocked_edit_becomes_a_request_with_its_reason(self):
        d = project()
        g = analyze.analyze(d)
        job = runner.Job(d, ["app/core"], "x", g, None)
        other = "app/api/handlers.py"
        job.events = [{"kind": "tool", "id": "t1", "name": "Edit", "detail": os.path.join(d, other)},
                      {"kind": "tool_result", "id": "t1", "denied": True, "text": f"modfence scope: {other} is outside"},
                      {"kind": "text", "text": f"Done inside.\nNEED {other}: pass the new field through\n"}]
        self.assertEqual(job.requests(), [{"path": other, "why": "pass the new field through"}])
        self.assertIn("NEED <path>", scope_guard.decide({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(d, other)}}, d, ["app/core"]))

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

    def test_versions_keep_prompt_and_revert(self):
        d = project()
        run_job(d, ["app/cli"], "explain only")  # no files changed: not a version
        job = run_job(d, ["app/core"], "edit app/core/values.py")
        vs = runner.versions(d)
        self.assertEqual(len(vs), 1)
        self.assertEqual((vs[0]["prompt"], vs[0]["modules"]), ("edit app/core/values.py", ["app/core"]))
        self.assertIn("app/api", vs[0]["ripple"])
        runner.revert_run(d, vs[0]["run"])
        self.assertEqual(runner.versions(d)[0]["reverted"], ["app/core/values.py"])

    def test_test_command_picks_pytest_unittest_or_override(self):
        d = project()
        self.assertEqual(runner.test_command(d)[1:4], ["-m", "unittest", "discover"])
        write(os.path.join(d, "conftest.py"), "")
        self.assertEqual(runner.test_command(d)[1:3], ["-m", "pytest"])
        os.environ["MODFENCE_TEST_CMD"] = "make test"
        try:
            self.assertEqual(runner.test_command(d), "make test")
        finally:
            del os.environ["MODFENCE_TEST_CMD"]
        e = tempfile.mkdtemp(prefix="modfence-test-")
        _dirs.append(e)
        self.assertIsNone(runner.test_command(e))
        self.assertIsNone(runner.run_tests(e)[0], "no tests: nothing to check, never a failure")

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
        rec = [json.loads(l) for l in analyze.read_text(os.path.join(d, ".modfence/runs/r1/checks.jsonl")).splitlines()]
        self.assertEqual([(r["ok"], r["blocked"]) for r in rec], [(False, 1), (False, 0)])

    def test_done_check_runs_the_tests_of_the_fence_and_its_users(self):
        d = project()
        ok = "import unittest\n{imp}\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
        write(os.path.join(d, "tests/__init__.py"), "")  # unittest discover needs a package since Python 3.11
        write(os.path.join(d, "tests/test_api.py"), ok.format(imp="from app.api.handlers import handle"))
        write(os.path.join(d, "tests/test_cli.py"), ok.format(imp="from app.cli.main import Cli"))
        write(os.path.join(d, "tests/test_fail.py"), "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('no')\n")
        g = analyze.analyze(d)
        self.assertEqual(runner.select_tests(g, ["app/core"]), {"files": ["tests/test_api.py", "tests/test_cli.py"],
                                                                 "fence": ["app/core"], "users": ["app/api", "app/cli"]})
        self.assertIsNone(runner.select_tests(g, ["app/broken"]), "no test imports it: the full suite runs")
        self.assertFalse(runner.run_tests(d)[0], "the full suite fails")
        self.assertTrue(runner.run_tests(d, files=["tests/test_api.py", "tests/test_cli.py"])[0])
        env = dict(os.environ, MODFENCE_ROOT=d, MODFENCE_RUN="r1", MODFENCE_SCOPE="app/core")
        hook = os.path.join(os.path.dirname(HERE), "modfence", "done_check.py")
        p = subprocess.run([sys.executable, hook], input="{}", capture_output=True, text=True, env=env)
        self.assertEqual(p.stdout.strip(), "", "the selected tests pass")
        rec = json.loads(analyze.read_text(os.path.join(d, ".modfence/runs/r1/checks.jsonl")))
        self.assertEqual((rec["ok"], rec["selected"]["files"], rec["selected"]["users"]),
                         (True, ["tests/test_api.py", "tests/test_cli.py"], ["app/api", "app/cli"]))

    def test_done_check_asks_once_for_a_test_of_new_branching_code(self):
        d = project()
        write(os.path.join(d, "tests/__init__.py"), "")
        write(os.path.join(d, "tests/test_api.py"), "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n")
        start = runner.fence_texts(d, ["app/core"])
        self.assertIn("tests/test_api.py", start, "tests are in the baseline even outside the fence")
        os.makedirs(os.path.join(d, ".modfence/runs/r2"))
        write(os.path.join(d, ".modfence/runs/r2/start.json"), json.dumps(start))
        write(os.path.join(d, "app/core/values.py"), "def clamp(x):\n    return x if x < LIMIT else LIMIT\n\ndef plain():\n    return 1\n", "a")
        now = runner.fence_texts(d, ["app/core"])
        self.assertEqual(runner.untested(start, now), ["app/core/values.py::clamp"], "plain() does not branch")
        env = dict(os.environ, MODFENCE_ROOT=d, MODFENCE_RUN="r2", MODFENCE_SCOPE="app/core")
        hook = os.path.join(os.path.dirname(HERE), "modfence", "done_check.py")
        first = subprocess.run([sys.executable, hook], input='{"stop_hook_active": false}', capture_output=True, text=True, env=env)
        self.assertIn("app/core/values.py::clamp", json.loads(first.stdout)["reason"])
        second = subprocess.run([sys.executable, hook], input='{"stop_hook_active": true}', capture_output=True, text=True, env=env)
        self.assertEqual(second.stdout.strip(), "", "a second stop is let through")
        rec = [json.loads(l) for l in analyze.read_text(os.path.join(d, ".modfence/runs/r2/checks.jsonl")).splitlines()]
        self.assertEqual([(r["ok"], r["blocked"], r["untested"]) for r in rec],
                         [(True, 1, ["app/core/values.py::clamp"]), (True, 0, ["app/core/values.py::clamp"])])
        write(os.path.join(d, "tests/test_api.py"), "# covers clamp\n", "a")
        self.assertEqual(runner.untested(start, runner.fence_texts(d, ["app/core"])), [], "a test changed: no gate")

    def test_a_run_drafts_its_commit_message(self):
        files = [{"path": "app/observer/cam.py", "status": "modified", "funcs": [
                     {"name": "frame_rate", "kind": "def", "status": "added"}, {"name": "capture", "kind": "def", "status": "changed"}]},
                 {"path": "app/ui/view.py", "status": "modified", "funcs": [{"name": "View.draw", "kind": "method", "status": "changed"}]},
                 {"path": "README.md", "status": "modified", "funcs": None}]
        self.assertEqual(runner.commit_message(files),
                         "observer: add frame_rate(); change capture()\n\n- app/ui/view.py: change View.draw()\n- README.md: modified")
        many = [{"path": "a/b.py", "status": "modified", "funcs": [{"name": f"function_{i}", "kind": "def", "status": "added"} for i in range(9)]}]
        subject = runner.commit_message(many)
        self.assertLessEqual(len(subject), 72)
        self.assertTrue(subject.startswith("a: add function_0(), ") and subject.endswith(" ..."))
        self.assertIsNone(runner.commit_message([]))
        d = project()
        job = run_job(d, ["app/core"], "edit app/core/values.py and edit README.md")
        ch = next(e for e in job.events if e["kind"] == "changes")
        self.assertEqual(ch["commit_message"], "core: update values.py\n\n- README.md: modified")
        self.assertEqual(runner.load_run(d, ch["run"])["commit_message"], ch["commit_message"])

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


class HandoffTest(unittest.TestCase):
    def test_the_map_as_text_for_agents_is_capped_and_deterministic(self):
        from modfence import handoff, roles
        d = project()
        g = analyze.analyze(d)
        self.assertIn("no module map yet", handoff.build(d, g), "no functions yet: a note, not an empty map")
        store = roles.to_store({f: ("core" if f.startswith("app/core") else "api") for f in roles.code_files(g)}, {"core": "Values."}, "test")
        store["areas"] = {"a1": {"name": "engine", "purpose": "Computes values.", "roles": ["r2"]},
                          "a2": {"name": "surface", "purpose": "Serves them.", "roles": ["r1"]}}
        roles.save_store(d, store)
        text = handoff.build(d, g)
        self.assertEqual(text, handoff.build(d, g))
        self.assertLessEqual(len(text), handoff.BUDGET)
        for want in ("## Functions", "- engine", "- surface", "roles: core", "surface -> engine: imports"):
            self.assertIn(want, text)


class WebTest(unittest.TestCase):
    """The page has no build step and no browser in CI: check what a typo or a cut too far would break."""

    def test_app_js_parses_and_every_called_view_function_exists(self):
        js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modfence", "web", "app.js"), encoding="utf-8").read()
        node = shutil.which("node")
        if node:
            p = subprocess.run([node, "--check", "-"], input=js, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 0, p.stderr[-500:])
        defined = set(re.findall(r"^(?:async )?function (\w+)\(", js, re.M)) | set(re.findall(r"^const (\w+) = \(", js, re.M))
        # functions the run log, the side bar and the map call by name: one cut too far broke a run's end once
        for name in ("renderReview", "renderLesson", "renderRequests", "renderChanges", "openSkills", "openFence", "route",
                     "readEdge", "linkPhrase", "drawFrame", "drawChip", "stressLayout", "placeFree", "boxName", "moveTip"):
            self.assertIn(name, defined, f"{name} is called but not defined")


class SkillsTest(unittest.TestCase):
    """No network: search, stars and fetch are replaced by fakes."""

    def setUp(self):
        self.d = project()
        write(os.path.join(self.d, "app/core/img.py"), "import PIL.Image\nimport numpy as np\nimport os, json\nfrom app.core import values\n")
        write(os.path.join(self.d, "app/api/web.py"), "from fastapi import FastAPI\nimport numpy\nfrom . import handlers\n")
        write(os.path.join(self.d, "requirements.txt"), "# deps\nfastapi>=0.100\nrequests==2.0  # http\n-e .\n")
        os.makedirs(os.path.join(self.d, "app/kernel"), exist_ok=True)
        write(os.path.join(self.d, "app/kernel/__init__.py"), "")
        write(os.path.join(self.d, "app/run.py"), "import kernel  # app/ on sys.path: the project's own package, not a library\n")
        self.saved = skills.search, skills.stars

    def tearDown(self):
        skills.search, skills.stars = self.saved

    def test_stack_from_imports_and_manifests(self):
        st = skills.stack(self.d, analyze.analyze(self.d))
        self.assertEqual(st["libs"], {"numpy": 2, "PIL": 1, "fastapi": 1}, "stdlib and the project's own packages are dropped")
        self.assertEqual(st["manifests"], {"fastapi": "requirements.txt", "requests": "requirements.txt"})
        self.assertEqual(st["group_kind"], "module")
        self.assertEqual(st["groups"]["app/core"], [["PIL", 1], ["numpy", 1]])

    def test_filter_and_rank(self):
        calls = []

        def fake_search(q):
            calls.append(q)
            hits = {"numpy": [("numpy-pro", "a/numpy", 5000), ("big-generic", "b/gen", 900000), ("tiny-numpy", "c/t", 999)],
                    "fastapi": [("fastapi-x", "d/fast", 2000), ("fastapi-lowstars", "e/low", 50000), ("numpy-pro", "a/numpy", 5000)],
                    "pillow": [("pillow-ratelimited", "f/rl", 3000)]}.get(q, [])
            return [{"id": f"{src}/{n}", "name": n, "source": src, "installs": i, "description": None,
                     "url": f"https://skills.sh/{src}/{n}"} for n, src, i in hits], None
        skills.search = fake_search
        skills.stars = lambda src: {"e/low": 10, "f/rl": None}.get(src, 500)
        g = analyze.analyze(self.d)
        r = skills.recommend(self.d, g)
        self.assertEqual(calls, ["numpy", "pillow", "fastapi", "requests", "python testing"])
        self.assertEqual([s["name"] for s in r["skills"]], ["numpy-pro", "pillow-ratelimited", "fastapi-x", "big-generic"],
                         "name matches first (by files using the library), then installs; <1000 installs and <100 stars dropped")
        self.assertEqual(r["skills"][0]["reason"], "used by 2 files in app/api and 1 more: numpy")
        self.assertIsNone(r["skills"][1]["stars"], "stars that cannot be read are N/A, and the skill is kept")
        self.assertEqual(r["skills"][0]["stars"], 500)
        skills.search = lambda q: self.fail("a second call within a day is served from the cache")
        self.assertEqual(skills.recommend(self.d, g)["skills"], r["skills"])
        skills.search = lambda q: ([], "search: URLError: offline")
        r = skills.recommend(self.d, g, refresh=True)
        self.assertEqual((r["skills"], len(r["errors"])), ([], 5))

    def test_install_validates_and_writes_only_the_skill(self):
        tree = {"tree": [{"path": "README.md", "type": "blob", "size": 5},
                         {"path": "skills/good/SKILL.md", "type": "blob", "size": 5},
                         {"path": "skills/good/ref/notes.md", "type": "blob", "size": 5},
                         {"path": "skills/other/SKILL.md", "type": "blob", "size": 5},
                         {"path": "skills/evil/SKILL.md", "type": "blob", "size": 5},
                         {"path": "skills/evil/../../../../x.txt", "type": "blob", "size": 5}]}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return json.dumps(tree).encode() if "/trees/" in url else b"data " + url.encode()
        self.assertEqual(skills.install(self.d, "o/r", "good", fetch=fetch), ["SKILL.md", "ref/notes.md"])
        home = os.path.join(self.d, ".claude", "skills", "good")
        self.assertTrue(os.path.isfile(os.path.join(home, "ref", "notes.md")))
        self.assertEqual(skills.installed(self.d), ["good"])
        self.assertFalse(any("README" in u or "other" in u for u in fetched))
        self.assertRaises(FileExistsError, skills.install, self.d, "o/r", "good", fetch=fetch)
        self.assertEqual(skills.install(self.d, "o/r", "good", replace=True, fetch=fetch), ["SKILL.md", "ref/notes.md"])
        n = len(fetched)
        self.assertRaises(ValueError, skills.install, self.d, "o/r", "evil", fetch=fetch)
        self.assertEqual(len(fetched), n + 1, "an unsafe path stops the install before any file is downloaded")
        self.assertFalse(os.path.exists(os.path.join(self.d, ".claude", "skills", "evil")))
        for src, name in (("o/r", ".."), ("../x", "good"), ("o/r", "a/b"), ("o/r/x", "good")):
            self.assertRaises(ValueError, skills.install, self.d, src, name, fetch=fetch)
        self.assertRaises(LookupError, skills.install, self.d, "o/r", "missing", fetch=fetch)


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

    def test_hand_a_task_to_your_own_agent_then_review_it(self):
        s, data = self.req("POST", "/api/hand?p=0", {"prompt": "double the limit", "scope": ["app/core"], "label": "core"}, {"X-Modfence": "1"})
        self.assertEqual(s, 200, data)
        res = json.loads(data)
        self.assertIn("double the limit", res["text"])
        self.assertIn("NEED <path>", runner.Handoff(self.d, ["app/core"], "x", analyze.analyze(self.d), None).system_note() + scope_guard.decide(
            {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(self.d, "app/cli/main.py")}}, self.d, ["app/core"]))
        self.assertEqual(load(os.path.join(self.d, ".modfence", "fence.json"))["files"], ["app/core"], "every agent in the project is fenced")
        write(os.path.join(self.d, "app/core/values.py"), "LIMIT = 20\n\ndef double(x):\n    return 2 * x\n")  # your agent's edit
        s, data = self.req("GET", f"/api/hand/status?p=0&job={res['job']}")
        self.assertEqual(json.loads(data)["changed"], ["app/core/values.py"])
        self.assertEqual(json.loads(self.req("GET", "/api/hand/active?p=0")[1])["job"], res["job"], "a reload finds the open hand-off")
        self.assertEqual(self.req("POST", "/api/hand/finish?p=0", {"job": res["job"]}, {"X-Modfence": "1"})[0], 200)
        s, stream = self.req("GET", f"/api/events?job={res['job']}&from=0")
        ch = next(json.loads(l[6:]) for l in stream.splitlines() if l.startswith("data: ") and '"changes"' in l)
        self.assertEqual(ch["modified"], ["app/core/values.py"])
        self.assertTrue(any(l.startswith("data: ") and '"result"' in l and '"ok": true' in l for l in stream.splitlines()),
                        "a reviewed hand-off reads Done, not Stopped")
        self.assertFalse(os.path.exists(os.path.join(self.d, ".modfence", "fence.json")), "the fence comes off after the review")
        self.assertEqual(json.loads(self.req("GET", "/api/hand/active?p=0")[1]), {}, "a reviewed hand-off is closed")

    def test_your_agent_hits_the_fence_and_you_allow_the_file(self):
        res = json.loads(self.req("POST", "/api/hand?p=0", {"prompt": "x", "scope": ["app/core"], "label": "core"}, {"X-Modfence": "1"})[1])
        env = {k: v for k, v in os.environ.items() if not k.startswith("MODFENCE_")}  # an agent the user started by hand
        hook = lambda path: subprocess.run([sys.executable, scope_guard.__file__, self.d], env=env, capture_output=True, text=True,
                                           input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(self.d, path)}}))
        self.assertEqual(hook("app/cli/main.py").returncode, 2)
        hook("app/api/routes.py")
        status = lambda: json.loads(self.req("GET", f"/api/hand/status?p=0&job={res['job']}")[1])
        self.assertEqual(status()["asks"], ["app/cli/main.py", "app/api/routes.py"], "each denied edit becomes a request card")
        s, data = self.req("POST", "/api/hand/answer?p=0", {"job": res["job"], "paths": ["app/cli/main.py"], "ok": True}, {"X-Modfence": "1"})
        self.assertIn("app/cli/main.py", json.loads(data)["scope"])
        self.req("POST", "/api/hand/answer?p=0", {"job": res["job"], "paths": ["app/api/routes.py"], "ok": False}, {"X-Modfence": "1"})
        self.assertEqual(status()["asks"], [], "answered requests leave")
        self.assertEqual(hook("app/cli/main.py").returncode, 0, "the allowed file is inside the fence now")
        self.assertEqual(hook("app/api/routes.py").returncode, 2, "a refused file stays outside")
        self.assertEqual(self.req("POST", "/api/fence/clear?p=0", {}, {"X-Modfence": "1"})[0], 409, "closing the panel keeps your agent fenced")
        self.req("POST", "/api/hand/finish?p=0", {"job": res["job"]}, {"X-Modfence": "1"})
        self.assertFalse(os.path.exists(os.path.join(self.d, scope_guard.ASKS_FILE)), "requests go with the fence")

    def test_handoff_and_brief_as_text(self):
        s, data = self.req("GET", "/api/handoff?p=0")
        self.assertEqual(s, 200)
        self.assertIn("text", json.loads(data))
        s, data = self.req("GET", "/api/brief?p=0&scope=app/core")
        self.assertEqual(s, 200)
        body = json.loads(data)
        self.assertGreater(body["tokens"], 0)
        self.assertIn("app/api", body["text"], "the brief names the modules that use the box")

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
        self.assertEqual(load(os.path.join(self.d, ".modfence", "fence.json"))["files"], ["app/cli"], "the ask sets the fence")
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
        self.assertFalse(os.path.exists(os.path.join(self.d, ".claude")), "a discarded run clears the fence")
        s, data = self.req("POST", "/api/approve?p=0", {"job": job, "paths": ["app/core/values.py"]}, {"X-Modfence": "1"})
        self.assertEqual(s, 200, data)
        s, stream = self.req("GET", f"/api/events?job={json.loads(data)['job']}&from=0")
        self.assertIn('"kind": "done"', stream)
        self.assertEqual(load(os.path.join(self.d, ".modfence", "fence.json"))["files"], ["app/cli", "app/core/values.py"],
                         "an approved request widens the fence and the run goes on")
        self.assertEqual(self.req("POST", "/api/approve?p=0", {"job": "nope", "paths": ["x"]}, {"X-Modfence": "1"})[0], 404)
        scope_guard.arm(self.d, ["app/cli"], True)
        self.assertEqual(self.req("POST", "/api/fence/clear?p=0", {}, {"X-Modfence": "1"})[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".modfence", "fence.json")))

    def test_skills_endpoints(self):
        saved = skills.search
        skills.search = lambda q: ([], "offline")
        try:
            s, data = self.req("GET", "/api/skills?p=0&refresh=1")
        finally:
            skills.search = saved
        self.assertEqual(s, 200, data)
        self.assertEqual({k for k in json.loads(data)}, {"skills", "queries", "errors", "at", "stack", "installed"})
        self.assertEqual(self.req("POST", "/api/skills/install?p=0", {"source": "o/r", "skill": "x"})[0], 403)
        self.assertEqual(self.req("POST", "/api/skills/install?p=0", {"source": "../r", "skill": "x"}, {"X-Modfence": "1"})[0], 400)


if __name__ == "__main__":
    unittest.main()
