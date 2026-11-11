"""Does stopping at a decision point cost less than guessing and being corrected? (EVALUATION.md, section 10)

Builds a toy project in a temporary folder (a config and a deterministic script that sleeps 0.05 s per epoch), then
for each task and arm runs `claude -p` with a simulated person:
- plain: the agent acts on its own guess; if config.json does not hold the person's goal afterwards, the person says
  "Not what I meant: I want KEY=VALUE. Fix it and rerun." in the same session, at most twice.
- mod: the same with this repository as a plugin (`--plugin-dir`). When an intent waits, the person picks the reading
  whose values hold the goal, or writes the goal in their own words; then the same correction rule.
The person's goal for each task is drawn once with random.Random(7) from plausible values. Writes one JSON line per run.

    python bench/rework_probe.py --runs 3 --out bench/results/rework.jsonl [--model claude-haiku-5-5] [--claude PATH]
"""
import argparse, json, os, random, shutil, subprocess, sys, tempfile, threading, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from modfence import mod  # noqa: E402

TRAIN = '''"""Toy experiment for a modfence probe: deterministic arithmetic, no data, no claims. Reads config.json.
It sleeps 0.05 s per epoch so that 'faster' has a meaning (fewer epochs)."""
import json, time
cfg = json.load(open("config.json"))
time.sleep(0.05 * cfg["epochs"])
score = round(1 - 1 / (1 + cfg["epochs"] * cfg["lr"] * 10), 4)
print(json.dumps({"seed": cfg["seed"], "epochs": cfg["epochs"], "lr": cfg["lr"], "score": score}))
'''
BASE = {"seed": 0, "epochs": 10, "lr": 0.01}
TASKS = [  # (id, prompt, plausible goals)
    ("H1", "train it longer and rerun", [("epochs", v) for v in (20, 30, 40, 50)]),
    ("H2", "use a smaller learning rate and rerun", [("lr", v) for v in (0.005, 0.001, 0.0005)]),
    ("H3", "make the training faster and rerun", [("epochs", 5), ("epochs", 2), ("lr", 0.05)]),
]


def same(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-12
    except (TypeError, ValueError):
        return False


def reset(p):
    json.dump(BASE, open(os.path.join(p, "config.json"), "w"))
    with open(os.path.join(p, "train.py"), "w", newline="\n") as f:
        f.write(TRAIN)
    shutil.rmtree(os.path.join(p, ".mod", "intents"), ignore_errors=True)
    mod.save_project(p, {"modules": [{"name": "experiment", "purpose": "The toy training run.", "paths": ["train.py", "config.json"]}], "settings": []})


def holds(p, goal):
    try:
        return same(json.load(open(os.path.join(p, "config.json"), encoding="utf-8")).get(goal[0]), goal[1])
    except (OSError, ValueError):
        return False


def person(p, goal, stop, log):
    while not stop.is_set():
        for i in mod.intents(p):
            if i.get("status") == "waiting":
                time.sleep(2)
                k = next((n for n, c in enumerate(i.get("candidates") or []) if same((c.get("differs") or {}).get(goal[0]), goal[1])), None)
                choice = {"kind": "pick", "index": k} if k is not None else {"kind": "own", "text": f"set {goal[0]} to {goal[1]}"}
                mod.answer(p, i["id"], choice)
                log.append({"readings": [(c.get("name"), c.get("differs")) for c in i.get("candidates") or []], "choice": choice})
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--arms", default="plain,mod")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--claude", default="claude")
    ap.add_argument("--out", default=os.path.join(REPO, "bench", "results", "rework.jsonl"))
    a = ap.parse_args()
    rng = random.Random(7)
    goals = {t: rng.choice(c) for t, _, c in TASKS}
    p = tempfile.mkdtemp(prefix="modfence-rework-")
    env = {**os.environ, "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}

    def claude(extra, prompt):
        t0 = time.time()
        r = subprocess.run([a.claude, "-p", "--model", a.model, "--permission-mode", "acceptEdits", "--allowedTools",
                            "Bash Read Edit Write Glob Grep", "--output-format", "json", *extra, prompt],
                           cwd=p, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            d = {"error": (r.stdout + r.stderr)[-300:]}
        return d, round(time.time() - t0, 1)

    for k in range(a.runs):
        for tid, prompt, _ in TASKS:
            goal = goals[tid]
            for arm in a.arms.split(","):
                reset(p)
                plug = ["--plugin-dir", REPO] if arm == "mod" else []
                stop, log = threading.Event(), []
                if arm == "mod":
                    threading.Thread(target=person, args=(p, goal, stop, log), daemon=True).start()
                steps = []
                d, secs = claude(plug, prompt + ". Reply in English.")
                steps.append({"cost": d.get("total_cost_usd"), "turns": d.get("num_turns"), "secs": secs, "ok": holds(p, goal),
                              "config": json.load(open(os.path.join(p, "config.json"), encoding="utf-8")), "result": (d.get("result") or d.get("error") or "")[:400]})
                while not steps[-1]["ok"] and len(steps) < 3 and d.get("session_id"):
                    d, secs = claude(plug + ["--resume", d["session_id"]], f"Not what I meant: I want {goal[0]}={goal[1]}. Fix it and rerun.")
                    steps.append({"cost": d.get("total_cost_usd"), "turns": d.get("num_turns"), "secs": secs, "ok": holds(p, goal),
                              "config": json.load(open(os.path.join(p, "config.json"), encoding="utf-8")), "result": (d.get("result") or d.get("error") or "")[:400]})
                stop.set()
                row = {"task": tid, "arm": arm, "run": k, "goal": goal, "model": a.model, "ok": steps[-1]["ok"],
                       "corrections": len(steps) - 1, "cost": round(sum(s["cost"] or 0 for s in steps), 5),
                       "secs": round(sum(s["secs"] for s in steps), 1), "turns": sum(s["turns"] or 0 for s in steps),
                       "stops": len(log), "page": log, "steps": steps}
                os.makedirs(os.path.dirname(a.out), exist_ok=True)
                with open(a.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                print(tid, arm, k, "ok", row["ok"], "corrections", row["corrections"], "cost", row["cost"], "secs", row["secs"], flush=True)
    shutil.rmtree(p, ignore_errors=True)


if __name__ == "__main__":
    main()
