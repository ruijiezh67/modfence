"""A stand-in for `claude -p --output-format stream-json` used by the tests. No model, no network.

It reads the prompt, emits the same event shapes Claude Code does (init, text deltas, a tool use and its
result, the final result), and makes the file changes the prompt asks for:
  "edit <path>"  writes a line to <path> (relative to the working directory)
It also records its argv to .modfence/fake_argv.json so tests can check the flags modfence passed.
"""
import json, os, sys


def out(obj):
    print(json.dumps(obj), flush=True)


def main():
    prompt = sys.stdin.read()
    os.makedirs(".modfence", exist_ok=True)
    with open(".modfence/fake_argv.json", "w") as fh:
        json.dump({"argv": sys.argv[1:], "scope": os.environ.get("MODFENCE_SCOPE")}, fh)
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
