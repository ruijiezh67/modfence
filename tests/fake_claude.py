"""A stand-in for `claude -p --output-format stream-json` used by the tests. No model, no network.

It reads the prompt, emits the same event shapes Claude Code does (init, text deltas, a tool use and its
result, the final result), and makes the file changes the prompt asks for:
  "edit <path>"  writes a line to <path> (relative to the working directory)
It also records its argv to .modfence/fake_argv.json so tests can check the flags modfence passed.
"""
import json, os, sys


def out(obj):
    print(json.dumps(obj), flush=True)


def describe(prompt):
    """--output-format json (purpose.describe): "Does <name>." for every name under each FILE, and the module."""
    obj, f = {"__module__": "Does the module's job."}, None
    for line in prompt.splitlines():
        if line.startswith("FILE "):
            f = line[5:]
        elif line.startswith("NAMES:") and f:
            obj[f] = {n.strip(): f"Does {n.strip()}." for n in line[6:].split(",") if n.strip()}
    print(json.dumps({"type": "result", "result": "```json\n" + json.dumps(obj) + "\n```", "total_cost_usd": 0.001}))


PLAN = {"questions": [{"q": "Keep the old name?", "options": ["Yes", "No"], "recommended": 0}],
        "plan": {"goal": "Double faster.", "functions": [{"file": "app/core/values.py", "name": "double", "change": "change", "why": "speed"}],
                 "done": "tests pass"}}


def main():
    prompt = sys.stdin.read()
    if "json" in sys.argv and sys.argv[sys.argv.index("json") - 1] == "--output-format":
        return describe(prompt)
    os.makedirs(".modfence", exist_ok=True)
    with open(".modfence/fake_argv.json", "w") as fh:
        json.dump({"argv": sys.argv[1:], "scope": os.environ.get("MODFENCE_SCOPE")}, fh)
    note = sys.argv[sys.argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in sys.argv else ""
    if "planning step" in note:  # answer like a planning run: JSON only
        out({"type": "system", "subtype": "init", "session_id": "fake-plan"})
        out({"type": "result", "subtype": "success", "is_error": False, "session_id": "fake-plan", "total_cost_usd": 0.0,
             "duration_ms": 900, "num_turns": 1, "result": "Here is the plan:\n" + json.dumps(PLAN)})
        return
    session = "fake-session-1"
    if "--resume" in sys.argv:
        session = sys.argv[sys.argv.index("--resume") + 1] + "-resumed"
    out({"type": "system", "subtype": "init", "session_id": session})
    for chunk in ("Looking at ", "the module."):
        out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": chunk}}})
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking at the module."}]}})
    for n, word in enumerate(prompt.split()):
        if word == "edit":
            path = prompt.split()[n + 1]
            tid = f"t{n}"
            out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Write", "input": {"file_path": path}}]}})
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a") as f:
                f.write("# edited by fake claude\n")
            out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "session_id": session, "total_cost_usd": 0.0,
         "duration_ms": 1200, "num_turns": 2, "result": "Looking at the module."})


if __name__ == "__main__":
    main()
