"""What does it cost to finish a whole cross-module feature, and is it right? Three ways to get it built:

  vibe         Claude Code alone, one run, the task text only. No module map, no fence: "just ask the model".
  fence-all    One modfence run fencing every module the task needs (module map in the system note + hook).
  fence-all-tests  Same as fence-all, with the tests module in the fence too (what an exercise sets up).
  fence-chain  One modfence run per module, foundations first; each run fences one module and is told which
               steps came before and which come after. This is the step-by-step way modfence is meant to be used.

Correctness is judged by bench/acceptance.py (black-box checks written from each task's Acceptance list), plus the
project's own tests. Cost and tokens are summed over all runs of a condition. Fresh project copy per attempt;
CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 so the operator's CLAUDE.md does not leak in.

Usage: python bench/feature_bench.py OUT.jsonl [--reps 2] [--jobs 3] [--only vibe,fence-all,fence-chain] [--tasks 01,04]
"""
import argparse, concurrent.futures as cf, json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from modfence import analyze, runner  # noqa: E402
from fence_bench import EXAMPLES, BenchJob, task_text  # noqa: E402
import acceptance  # noqa: E402

# (example, TASKS.md section, modules the feature touches, in dependency order: foundations first)
TASKS = [
    ("01-calculator", 4, ["calc/lexer", "calc/parser", "calc/evaluator"]),
    ("02-library", 4, ["library/domain", "library/storage", "library/services", "library/cli"]),
    ("03-spreadsheet", 4, ["sheet/formula", "sheet/functions", "sheet/engine", "sheet/io"]),
    ("04-tinygpt", 4, ["tinygpt/config", "tinygpt/train"]),
]
TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def run_job(root, scope, prompt, condition, claude):
    job = BenchJob(root, scope, prompt, analyze.analyze(root), claude)
    job.condition = condition
    job._run()
    res = next((e for e in job.events if e["kind"] == "result"), {})
    ch = next((e for e in job.events if e["kind"] == "changes"), {})
    return {"cost_usd": res.get("cost_usd"), "turns": res.get("turns"), "usage": res.get("usage") or {}, "model": res.get("model"),
            "ok": res.get("ok"), "changed": [f["path"] for f in ch.get("files", [])],
            "outside": ch.get("outside_scope"), "blocked": sum(1 for e in job.events if e["kind"] == "tool_result" and e.get("denied")),
            "errors": [e["text"][:200] for e in job.events if e["kind"] == "error"]}


def attempt(example, num, chain, condition, rep, workdir, claude):
    root = os.path.join(workdir, f"{example}-{condition}-{rep}")
    pristine = os.path.join(EXAMPLES, example)
    shutil.copytree(pristine, root, ignore=shutil.ignore_patterns(".modfence", "__pycache__"))
    task = task_text(example, num)
    t0, steps = time.time(), []
    if condition == "vibe":
        steps.append(run_job(root, ["."], task, "plain", claude))  # "plain" = no note; no fence sentence, no hook
    elif condition == "fence-all":
        steps.append(run_job(root, chain, task, "modfence", claude))
    elif condition == "fence-all-tests":  # the fence a user gets from an exercise: its modules plus the tests
        tests = [m["id"] for m in analyze.analyze(root)["modules"] if m["kind"] == "tests"]
        steps.append(run_job(root, chain + tests, task, "modfence", claude))
    else:
        for i, m in enumerate(chain):
            note = f"\n\nThis is step {i + 1} of {len(chain)}. In this run, build only the part of the feature that belongs in `{m}`."
            if chain[:i]:
                note += " Earlier steps already did their part in: " + ", ".join(f"`{x}`" for x in chain[:i]) + "."
            if chain[i + 1:]:
                note += " Later steps will do: " + ", ".join(f"`{x}`" for x in chain[i + 1:]) + ". The tests may only pass after the last step."
            steps.append(run_job(root, [m], task + note, "modfence", claude))
    checks = acceptance.check(example, root, pristine)
    tests_ok, tests_summary, _ = runner.run_tests(root, timeout=300)
    costs = [s["cost_usd"] for s in steps]
    row = {
        "example": example, "task": num, "condition": condition, "rep": rep, "runs": len(steps),
        "acceptance_passed": sum(ok for _, ok, _ in checks), "acceptance_total": len(checks),
        "acceptance": [[n, ok, d[:200]] for n, ok, d in checks],
        "tests_ok": tests_ok, "tests_summary": tests_summary,
        "cost_usd": None if None in costs else round(sum(costs), 4),  # N/A if any run did not report a cost
        "turns": sum(s["turns"] or 0 for s in steps),
        "tokens": {k: sum((s["usage"].get(k) or 0) for s in steps) for k in TOKEN_KEYS},
        "outside_fence": [p for s in steps for p in (s["outside"] or [])] if condition != "vibe" else None,
        "blocked_edits": sum(s["blocked"] for s in steps), "wall_s": round(time.time() - t0, 1),
        "steps": steps,
    }
    shutil.rmtree(root, ignore_errors=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--only", default="vibe,fence-all,fence-chain")
    ap.add_argument("--tasks", default="")
    a = ap.parse_args()
    os.environ["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    claude = runner.find_claude()
    workdir = tempfile.mkdtemp(prefix="featurebench-")
    tasks = [t for t in TASKS if not a.tasks or t[0][:2] in a.tasks.split(",")]
    plan = [(ex, n, ch, c, r) for ex, n, ch in tasks for c in a.only.split(",") for r in range(a.reps)]
    print(f"{len(plan)} attempts, claude={claude}, workdir={workdir}", flush=True)
    with cf.ThreadPoolExecutor(a.jobs) as pool, open(a.out, "a", encoding="utf-8") as out:
        futs = {pool.submit(attempt, *p, workdir, claude): p for p in plan}
        for f in cf.as_completed(futs):
            try:
                row = f.result()
            except Exception as e:  # recorded, not hidden
                ex, n, ch, c, r = futs[f]
                row = {"example": ex, "task": n, "condition": c, "rep": r, "crash": repr(e)[:300]}
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(json.dumps({k: row.get(k) for k in ("example", "condition", "rep", "runs", "acceptance_passed", "acceptance_total", "tests_ok", "cost_usd", "turns", "crash")}), flush=True)
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
