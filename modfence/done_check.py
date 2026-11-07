"""Claude Code Stop hook for build runs: the agent may not finish while the project's tests fail.

The first failing check blocks the stop and hands the agent the test output. A second stop (stop_hook_active) is let
through whatever the result, so a run cannot loop and burn tokens; the result is still recorded, and modfence marks
the run "done check failed". Every check is appended to .modfence/runs/<MODFENCE_RUN>/checks.jsonl.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modfence.runner import RUN_ID, run_tests  # noqa: E402


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    root, run = os.environ.get("MODFENCE_ROOT", "."), os.environ.get("MODFENCE_RUN", "")
    ok, summary, out = run_tests(root)
    if ok is None:  # no tests: nothing to check
        return
    block = not ok and not event.get("stop_hook_active")
    if RUN_ID.match(run):
        d = os.path.join(root, ".modfence", "runs", run)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "checks.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ok": ok, "summary": summary, "blocked": int(block)}) + "\n")
    if block:
        print(json.dumps({"decision": "block", "reason": "Done check: the project's tests fail (" + summary + "). "
                          "Fix them inside the fence, or stop and explain why they cannot pass.\n\n" + out[-2000:]}))


if __name__ == "__main__":
    main()
