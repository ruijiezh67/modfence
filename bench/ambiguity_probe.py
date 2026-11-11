"""Ambiguous one-constant requests on TinyDB: stop-and-ask vs guess-and-correct (EVALUATION.md, section 10).

Needs a clone of TinyDB (github.com/msiemens/tinydb) at edff96a with `.mod/project.mod` saved from the map. Each task
leaves one constant open; the person's goal is drawn once with random.Random(7) and checked by a regex on the source
afterwards. Nothing in TinyDB is run: `--restricted` removes every code-running tool, so the plugin's agent writes its
intent and ends its turn, and the simulated person answers on the page and says "continue". A wrong result gets
"Not what I meant: <the person's words>" (at most twice). The committed results were run without --restricted and
--strict-mcp-config (Bash was disallowed instead).

    python bench/ambiguity_probe.py --repo PATH/tinydb --runs 3 [--claude PATH] [--out bench/results/ambiguity.jsonl]
"""
import argparse, json, os, random, re, subprocess, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from modfence import mod  # noqa: E402

TASKS = [  # id, prompt, file, regex for the value, plausible goals, how the person says it
    ("K1", "make the query cache bigger", "tinydb/table.py", r"default_query_cache_capacity\s*=\s*(\d+)",
     [20, 50, 100, 1000], "the default query cache should hold {} queries"),
    ("K2", "use a shorter name for the default table", "tinydb/database.py", r"default_table_name\s*=\s*['\"]([^'\"]*)['\"]",
     ["default", "main", "db"], "name the default table '{}'"),
    ("K3", "make the caching middleware write to disk more often", "tinydb/middlewares.py", r"WRITE_CACHE_SIZE\s*=\s*(\d+)",
     [10, 100, 250, 500], "write to disk every {} changes"),
]
ap = argparse.ArgumentParser()
ap.add_argument("--repo", required=True)
ap.add_argument("--runs", type=int, default=1)
ap.add_argument("--arms", default="plain,mod")
ap.add_argument("--claude", default="claude")
ap.add_argument("--model", default="claude-haiku-5-5")
ap.add_argument("--out", default=os.path.join(REPO, "bench", "results", "ambiguity.jsonl"))
a = ap.parse_args()
P, CL, PLUG, OUT, runs, arms = os.path.abspath(a.repo), a.claude, REPO, a.out, a.runs, a.arms.split(",")
rng = random.Random(7)
GOALS = {t[0]: rng.choice(t[4]) for t in TASKS}
TAIL = " Do not run anything (no tests, no scripts); only read and edit the code. Reply in English, one short paragraph."
env = {**os.environ, "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}


def git(*a):
    return subprocess.run(["git", *a], cwd=P, capture_output=True, text=True, encoding="utf-8").stdout


def value(task):
    m = re.search(task[3], open(os.path.join(P, task[2]), encoding="utf-8").read())
    return m.group(1) if m else None


def same(a, b):
    return str(a).strip().strip("'\"") == str(b)


def claude(extra, prompt):
    t0 = time.time()
    r = subprocess.run([CL, "-p", "--restricted", "--strict-mcp-config", "--model", a.model, "--permission-mode", "acceptEdits",
                        "--output-format", "json", *extra, prompt],
                       cwd=P, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"error": (r.stdout + r.stderr)[-300:]}
    return d, round(time.time() - t0, 1)


for k in range(runs):
    for task in TASKS:
        tid, prompt, goal, say = task[0], task[1], GOALS[task[0]], task[5].format(GOALS[task[0]])
        for arm in arms:
            git("checkout", "--", "."); git("clean", "-fdq")
            for f in os.listdir(os.path.join(P, ".mod", "intents")) if os.path.isdir(os.path.join(P, ".mod", "intents")) else []:
                os.remove(os.path.join(P, ".mod", "intents", f))
            for f in (".modfence/fence.json", ".modfence/asks.jsonl"):
                if os.path.exists(os.path.join(P, f)):
                    os.remove(os.path.join(P, f))
            proj = mod.load_project(P)
            mod.save_project(P, {**proj, "settings": []})
            plug = ["--plugin-dir", PLUG] if arm != "plain" else []
            steps, page = [], []
            d, secs = claude(plug, prompt + "." + TAIL)
            steps.append({"cost": d.get("total_cost_usd"), "turns": d.get("num_turns"), "secs": secs, "value": value(task), "result": (d.get("result") or d.get("error") or "")[:300]})
            sid = d.get("session_id")
            if arm != "plain":
                open_ = [i for i in mod.intents(P) if i.get("status") != "answered"]
                if open_ and sid:  # the person answers on the page, then says continue
                    i = open_[0]
                    kk = next((n for n, c in enumerate(i.get("candidates") or []) if any(same(v, goal) for v in (c.get("differs") or {}).values())), None)
                    choice = {"kind": "pick", "index": kk} if kk is not None else {"kind": "own", "text": say}
                    mod.answer(P, i["id"], choice)
                    page.append({"readings": [(c.get("name"), c.get("differs")) for c in i.get("candidates") or []], "choice": choice})
                    d, secs = claude(plug + ["--resume", sid], "continue")
                    steps.append({"cost": d.get("total_cost_usd"), "turns": d.get("num_turns"), "secs": secs, "value": value(task), "result": (d.get("result") or d.get("error") or "")[:300], "after_page": True})
            corrections = 0
            while not same(steps[-1]["value"], goal) and corrections < 2 and sid:
                d, secs = claude(plug + ["--resume", sid], f"Not what I meant: {say}. Fix it.")
                corrections += 1
                steps.append({"cost": d.get("total_cost_usd"), "turns": d.get("num_turns"), "secs": secs, "value": value(task), "result": (d.get("result") or d.get("error") or "")[:300]})
            row = {"task": tid, "arm": arm, "run": k, "goal": goal, "ok": same(steps[-1]["value"], goal), "corrections": corrections,
                   "stops": len(page), "cost": round(sum(s["cost"] or 0 for s in steps), 5), "secs": round(sum(s["secs"] for s in steps), 1),
                   "turns": sum(s["turns"] or 0 for s in steps), "files": git("diff", "--stat").strip().splitlines()[:-1], "page": page, "steps": steps}
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            print(tid, arm, k, "goal", goal, "ok", row["ok"], "stops", row["stops"], "corr", corrections, "cost", row["cost"], "secs", row["secs"], flush=True)
git("checkout", "--", "."); git("clean", "-fdq")
