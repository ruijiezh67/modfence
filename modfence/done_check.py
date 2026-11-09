"""Claude Code Stop hook for build runs: the agent may not finish while the project's tests fail.

It runs the test files that import the fence or the modules using it (all tests when none do). The first failing
check blocks the stop and hands the agent the test output. The first stop is also blocked when the run added or
changed a function that branches or loops and no test file changed: the agent is asked for one test. A second stop
(stop_hook_active) is let through whatever the result, so a run cannot loop and burn tokens; the result is still
recorded, and modfence marks the run "done check failed". Every check is appended to
.modfence/runs/<MODFENCE_RUN>/checks.jsonl.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence import analyze, runner  # noqa: E402


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    root, run = os.environ.get("MODFENCE_ROOT", "."), os.environ.get("MODFENCE_RUN", "")
    scope = [s for s in os.environ.get("MODFENCE_SCOPE", "").split(os.pathsep) if s]
    selected = runner.select_tests(analyze.analyze(root), scope) if isinstance(runner.test_command(root), list) else None
    ok, summary, out = runner.run_tests(root, files=selected and selected["files"])
    if ok is None:  # no tests: nothing to check
        return
    d = runner.run_dir(root, run) if runner.RUN_ID.match(run) else None
    try:
        start = json.loads(analyze.read_text(os.path.join(d, "start.json"))) if d else None
    except (OSError, ValueError):
        start = None  # not a modfence build run: no baseline, no test gate
    gaps = runner.untested(start, runner.fence_texts(root, scope)) if start is not None else []
    block = (not ok or bool(gaps)) and not event.get("stop_hook_active")
    if d:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "checks.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ok": ok, "summary": summary, "blocked": int(block), "selected": selected,
                                "untested": gaps}) + "\n")
    if not block:
        return
    if not ok:
        reason = ("Done check: the project's tests fail (" + summary + "). "
                  "Fix them inside the fence, or stop and explain why they cannot pass.\n\n" + out[-2000:])
    else:
        reason = ("Done check: the tests pass, but no test changed in this run and these functions branch or loop: "
                  + ", ".join(gaps) + ". Add or update one test that covers them (if the tests are outside your fence, "
                  "end with NEED <test file>: <the test>), then stop.")
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
