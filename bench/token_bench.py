"""Does module vibe coding save tokens on a real library? Plain Claude Code against a sealed modfence run, on the four
rich tasks in bench/token_tasks.py (golden rules 4 and 7; the experiment the survey in research notes calls A0 vs A2).

  vibe    Claude Code alone, the task spec only: "just ask the model".
  plain   Claude Code alone. Prompt: the task spec plus "The change belongs in `<module>`." No note, no hooks.
  sealed  modfence: the same prompt; fence = the module; the system note carries the brief; other modules' code is
          hidden. Without the lean rule (runner.LEAN_RULE), as measured before it existed.
  lean    sealed plus the lean rule (golden rule 7, built in since 2026-11-09). (Round 1 also fenced the tests and its note invited test writing; see docs/EVALUATION.md.)

Same prompt text, same fresh copy of rich (no .git) per attempt, CLAUDE_CODE_DISABLE_CLAUDE_MDS=1, no plan step and no
done check in either arm (so only the context differs). After the run, the hidden acceptance tests and rich's own test
file for that module are run. Recorded per attempt: billed tokens by kind, cost, turns, tool calls by name, reads of
other modules' code, denied calls, acceptance k/n, regression pass, wall time. Nothing unmeasured is written as 0.

Usage: python bench/token_bench.py RICH_DIR OUT.jsonl [--reps 2] [--jobs 3] [--only plain,sealed] [--tasks T1,T3]
"""
import argparse, concurrent.futures as cf, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from modfence import analyze, runner  # noqa: E402
from fence_bench import BenchJob  # noqa: E402
from token_tasks import TASKS  # noqa: E402

TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def pytest(root, files):
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=root,
                       capture_output=True, text=True, timeout=300)
    last = (p.stdout.strip().splitlines() or [""])[-1]
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", last)) else 0
    failed = sum(int(x) for x in re.findall(r"(\d+) (?:failed|error)", last))
    return p.returncode == 0, passed, passed + failed, last


def attempt(rich, name, arm, rep, workdir, claude):
    t = TASKS[name]
    root = os.path.join(workdir, f"{name}-{arm}-{rep}")
    shutil.copytree(rich, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".modfence"))
    prompt = t["spec"] + ("" if arm == "vibe" else f"\n\nThe change belongs in `{t['module']}`.")
    graph = analyze.analyze(root)
    job = BenchJob(root, [t["module"]], prompt, graph, claude, seal=(arm in ("sealed", "lean")), lean=(arm == "lean"))
    job.condition = "modfence" if arm in ("sealed", "lean") else "plain"
    t0 = time.time()
    job._run()
    ev = job.events
    res = next((e for e in ev if e["kind"] == "result"), {})
    tools = [e for e in ev if e["kind"] == "tool"]
    other_reads = [e["detail"] for e in tools if e["name"] == "Read" and e["detail"].endswith(".py")
                   and t["module"] not in e["detail"].replace("\\", "/") and "/tests/" not in e["detail"].replace("\\", "/")]
    acc_path = os.path.join(root, "tests", "test_accept_bench.py")
    with open(acc_path, "w", encoding="utf-8") as f:
        f.write(t["accept"])
    acc_ok, acc_k, acc_n, acc_last = pytest(root, ["tests/test_accept_bench.py"])
    reg_ok, _, _, reg_last = pytest(root, [t["regression"]])
    usage = res.get("usage") or {}
    row = {
        "task": name, "arm": arm, "rep": rep, "module": t["module"],
        "rich_commit": subprocess.run(["git", "-C", rich, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "run_ok": res.get("ok"), "cost_usd": res.get("cost_usd"), "turns": res.get("turns"), "model": res.get("model"),
        "tokens": {k: usage.get(k) for k in TOKEN_KEYS},  # None (N/A) when the CLI did not report it
        "tools": {n: sum(1 for e in tools if e["name"] == n) for n in sorted({e["name"] for e in tools})},
        "steps": [f"{e['name']}: {e['detail'][:100]}" for e in tools][:60],
        "other_module_reads": len(other_reads), "other_module_read_paths": other_reads[:30],
        "denied": sum(1 for e in ev if e["kind"] == "tool_result" and e.get("denied")),
        "accept_passed": acc_k, "accept_total": acc_n, "accept_ok": acc_ok, "accept_last": acc_last,
        "regression_ok": reg_ok, "regression_last": reg_last, "wall_s": round(time.time() - t0, 1),
        "errors": [e["text"][:300] for e in ev if e["kind"] == "error"],
    }
    shutil.rmtree(root, ignore_errors=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rich")
    ap.add_argument("out")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--only", default="vibe,plain,sealed")
    ap.add_argument("--tasks", default="")
    a = ap.parse_args()
    os.environ["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    claude = runner.find_claude()
    workdir = tempfile.mkdtemp(prefix="tokenbench-")
    names = [n for n in TASKS if not a.tasks or n.split("-")[0] in a.tasks.split(",")]
    plan = [(n, arm, r) for r in range(a.reps) for n in names for arm in a.only.split(",")]
    print(f"{len(plan)} attempts, claude={claude}, workdir={workdir}", flush=True)
    with cf.ThreadPoolExecutor(a.jobs) as pool, open(a.out, "a", encoding="utf-8") as out:
        futs = {pool.submit(attempt, a.rich, *p, workdir, claude): p for p in plan}
        for f in cf.as_completed(futs):
            try:
                row = f.result()
            except Exception as e:  # recorded, not hidden
                n, arm, r = futs[f]
                row = {"task": n, "arm": arm, "rep": r, "crash": repr(e)[:300]}
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(json.dumps({k: row.get(k) for k in ("task", "arm", "rep", "cost_usd", "turns", "other_module_reads", "denied", "accept_passed", "accept_total", "regression_ok", "crash")}), flush=True)
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
