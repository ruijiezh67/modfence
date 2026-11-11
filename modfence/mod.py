""".mod: modfence's own files for what an agent must not guess (golden rules 1, 4 and 6). People never read them; the
page (web/mod.html) shows them, and agents read a compact rendering instead of long conversation memory.

    <project>/.mod/project.mod          the modules, settings the person confirmed, remembered facts with their dates
    <project>/.mod/intents/<id>.mod     one per intent: the person's words, 2-3 readings, every setting with its
                                        source (user, default, memory, guess), the scale, a plan slice, the answer

JSON, so the page and any agent read them without a parser of ours. `.mod/` is git-ignored by default (a `*` in
`.mod/.gitignore`); delete that file to share the folder with a team. project.mod replaces MODULES.md, which is read
once, as it was, when a project has no project.mod yet.
"""
import json, os, re, time
from datetime import datetime

DIR = ".mod"
PROJECT = "project.mod"
SOURCES = ("user", "default", "memory", "guess")
WAIT_S = 110  # ponytail: inside Claude Code's default 2-minute Bash timeout and the 5-minute prompt-cache life; waiting costs no tokens
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def _dir(root, *parts):
    return os.path.join(root, DIR, *parts)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(root, path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gi = _dir(root, ".gitignore")
    if not os.path.exists(gi):  # default: stays on this machine; deleting this file shares .mod/ through git
        with open(gi, "w", newline="\n") as f:
            f.write("*\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)  # the page and a waiting agent never read half a file


def today():
    return datetime.now().astimezone().date().isoformat()


# ---------- the project ----------
def load_project(root):
    """project.mod, else one built from MODULES.md (not written until something changes), else None."""
    p = _read(_dir(root, PROJECT))
    if p is not None:
        p.setdefault("modules", None)
        p.setdefault("settings", [])
        return p
    from . import modules
    legacy = modules.load_markdown(root)
    if legacy is None:
        return None
    return {"mod": 1, "kind": "project", "modules": legacy, "settings": []}


def save_project(root, project):
    project = {"mod": 1, "kind": "project", **project}
    _write(root, _dir(root, PROJECT), project)


def has_project(root):
    return os.path.isfile(_dir(root, PROJECT)) or os.path.isfile(os.path.join(root, "MODULES.md"))


def confirm(root, settings):
    """Settings the person confirmed become the project's: never asked again until they change."""
    p = load_project(root) or {"modules": None, "settings": []}
    by = {s["key"]: s for s in p["settings"]}
    for s in settings:
        by[s["key"]] = {"key": s["key"], "value": s["value"], "source": "user", "at": today()}
    p["settings"] = list(by.values())
    save_project(root, p)


# ---------- intents ----------
def intent_path(root, iid):
    if not ID.match(iid or ""):
        raise ValueError(f"bad intent id: {iid!r}")
    return _dir(root, "intents", iid + ".mod")


def load_intent(root, iid):
    return _read(intent_path(root, iid))


def save_intent(root, iid, intent):
    _write(root, intent_path(root, iid), intent)


def intents(root):
    """Every intent, newest first, each with its id."""
    d = _dir(root, "intents")
    out = []
    for f in os.listdir(d) if os.path.isdir(d) else []:
        if f.endswith(".mod"):
            i = _read(os.path.join(d, f))
            if isinstance(i, dict):
                out.append({**i, "id": f[:-4], "mtime": os.path.getmtime(os.path.join(d, f))})
    return sorted(out, key=lambda i: -i["mtime"])


def problems(intent):
    """What an agent got wrong in an intent file, in words it can fix; [] when it is usable."""
    if not isinstance(intent, dict):
        return ["not a JSON object"]
    out = []
    if not str(intent.get("words") or "").strip():
        out.append('"words": the user\'s exact words are missing')
    cands = intent.get("candidates") or []
    if not 2 <= len(cands) <= 3:
        out.append('"candidates": give 2 or 3 distinct readings')
    for i, c in enumerate(cands):
        if not isinstance(c, dict) or not c.get("name") or not c.get("evidence"):
            out.append(f'"candidates"[{i}]: needs "name" and "evidence" (a file:line, a diff line or the user\'s words)')
    for i, s in enumerate(intent.get("settings") or []):
        if not isinstance(s, dict) or "key" not in s or s.get("source") not in SOURCES:
            out.append(f'"settings"[{i}]: needs "key", "value" and "source" (one of {", ".join(SOURCES)})')
        elif s["source"] == "memory" and not s.get("at"):
            out.append(f'"settings"[{i}] ({s["key"]}): a remembered value needs "at", the date it is from')
    return out


def answer(root, iid, choice, edits=None):
    """The person's answer from the page: choice = {"kind": "pick"|"own", "index"|"text", and optionally "name" and
    "description" (an edited reading), "differs" {key: value} (values of the picked reading the person changed),
    "weights" {index: 1-10}, "deleted" [index]}; edits = {key: value}.
    Picked or edited settings are confirmed for the project."""
    intent = load_intent(root, iid)
    if intent is None:
        raise LookupError(f"no intent {iid}")
    if choice.get("kind") == "pick":
        n = len(intent.get("candidates") or [])
        if not isinstance(choice.get("index"), int) or not 0 <= choice["index"] < n:
            raise ValueError("pick one of the readings")
    elif choice.get("kind") != "own" or not str(choice.get("text") or "").strip():
        raise ValueError("pick a reading or write your own")
    for s in intent.get("settings") or []:
        if s["key"] in (edits or {}):
            s.update(value=edits[s["key"]], source="user", at=today(), edited=True)
    intent.update(status="answered", choice={**choice, "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    save_intent(root, iid, intent)
    confirm(root, [s for s in intent.get("settings") or [] if s.get("edited") or s["source"] in ("guess", "memory")])
    return intent


def reply(intent):
    """What the waiting agent reads: the reading to follow and the settings to use, nothing else."""
    c = intent["choice"]
    if c["kind"] == "pick" and c.get("name"):  # Lam's Edit: the person's wording replaces the agent's, verbatim
        head = f'The user edited a reading; use it verbatim: "{c["name"]}"' + (f' ({c["description"]})' if c.get("description") else "")
    elif c["kind"] == "pick":
        head = f'The user picked: "{intent["candidates"][c["index"]]["name"]}"'
    else:
        head = f'The user wrote their own goal, use it verbatim: "{c["text"]}"'
    if c["kind"] == "pick":  # the picked reading's own values, so the agent need not recall them
        cand = intent["candidates"][c["index"]]
        mine = {s["key"] for s in intent.get("settings") or [] if s.get("edited")}  # a value the person typed wins
        vals = {k: v for k, v in {**(cand.get("differs") or {}), **(c.get("differs") or {})}.items() if k not in mine}
        if vals:
            head += ". Its values: " + "; ".join(f"{k}={v}" + (" (changed by the user)" if k in (c.get("differs") or {}) else "") for k, v in vals.items())
        sc = cand.get("scale") or intent.get("scale")
        if sc and sc.get("pick"):
            head += f'. Scale: {sc["pick"]}' + (f', {sc["runs"]} runs' if sc.get("runs") is not None else "")
    if c.get("weights"):
        head += ". How much each reading matters to the user (1-10): " + "; ".join(
            f'{intent["candidates"][int(k)]["name"]}={w}' for k, w in c["weights"].items() if 0 <= int(k) < len(intent["candidates"]))
    if c.get("deleted"):
        head += ". Readings the user deleted as wrong: " + "; ".join(intent["candidates"][k]["name"] for k in c["deleted"] if 0 <= k < len(intent["candidates"]))
    rows = [f'{s["key"]}={s["value"]}' + (" (changed by the user)" if s.get("edited") else "") for s in intent.get("settings") or []]
    return head + ". Settings: " + ("; ".join(rows) or "none") + ". Follow exactly this; ask again only if it turns out impossible."


def wait(root, iid, seconds=WAIT_S, poll=1.0):
    """Block until the person answers on the page. (exit code, text for the agent)."""
    intent = load_intent(root, iid)
    if intent is None:
        return 2, f"modfence: no {DIR}/intents/{iid}.mod; write it first."
    bad = problems(intent)
    if bad:
        return 2, "modfence: fix the intent file, then run this again: " + "; ".join(bad)
    if intent.get("status") != "answered":
        intent["status"] = "waiting"
        save_intent(root, iid, intent)
    end = time.time() + seconds
    while True:
        intent = load_intent(root, iid) or intent
        if intent.get("status") == "answered":
            return 0, reply(intent)
        if time.time() >= end:
            break
        time.sleep(poll)
    return 3, ("modfence: the user has not answered on the page yet. Stop here, say in one line that the readings are "
               "waiting on the modfence page, and continue when they answer.")


# ---------- what an agent reads instead of conversation memory ----------
PROTOCOL = ("When the user states an intent whose settings they did not all give (a new task or experiment from a short "
            "prompt, before writing an experiment config, before running an experiment, before writing results into docs, "
            "before something hard to undo, or when two readings are plausible), do not guess silently: write "
            "{dir}/intents/<yyyymmdd-hhmm-slug>.mod as JSON {{\"words\": the user's exact words, \"candidates\": 2-3 distinct "
            "readings [{{\"name\", \"description\", \"weight\": 1-10, \"evidence\", \"differs\": {{setting: value}}, \"scale\" if it differs}}], "
            "\"settings\": [{{\"key\", \"value\", \"source\": user|default|memory|guess, \"at\": date if memory, \"from\": the "
            "user's words it comes from or null}}], \"scale\": {{\"pick\": one|sample|full, \"runs\", \"cost\", \"time\"}}, "
            "\"plan\": [\"prev step\", \"this step\", \"next step\"]}}, then run `{cmd} mod wait <id>` and follow its answer. "
            "First read the code and the confirmed settings; ask only what they cannot settle. Write every field in English (translate the user's words if they are in another language). Never mark a reading "
            "as recommended. Skip this for clear small edits.")


def context(root, cmd="modfence"):
    """The compact project state for an agent's context: modules by name, confirmed settings, the open intent."""
    p = load_project(root)
    if p is None:
        return ""
    lines = ["modfence project state (from .mod; trust it over older memory):"]
    if p.get("modules"):
        lines.append("modules: " + "; ".join(f'{m["name"]} ({m["purpose"]})' if m.get("purpose") else m["name"] for m in p["modules"]))
    if p.get("settings"):
        lines.append("confirmed by the user, do not ask again: " + "; ".join(f'{s["key"]}={s["value"]} ({s.get("at", "")})' for s in p["settings"]))
    for i in intents(root)[:1]:
        if i.get("status") == "answered":
            lines.append(f'last intent {i["id"]}: ' + reply(i))
        elif i.get("status") == "waiting":
            lines.append(f'intent {i["id"]} is waiting for the user on the modfence page; run `{cmd} mod wait {i["id"]}` before acting on it.')
    lines.append(PROTOCOL.format(dir=DIR, cmd=cmd))
    return "\n".join(lines)


def main(argv):
    """modfence mod show | context | wait <id> [--seconds N] | session-hook"""
    root = os.getcwd()
    from .jit import project_root
    root = project_root(root) or root
    if argv[:1] == ["wait"] and len(argv) > 1:
        secs = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else WAIT_S
        code, text = wait(root, argv[1], secs)
        print(text)
        return code
    if argv[:1] == ["context"]:
        print(context(root))
        return 0
    if argv[:1] == ["session-hook"]:  # SessionStart, also after compaction: the state comes back from .mod, not a summary
        plugin = os.environ.get("CLAUDE_PLUGIN_ROOT")
        text = context(root, f'python "{plugin.replace(os.sep, "/")}/plugin/cli.py"' if plugin else "modfence")
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
        return 0
    for i in intents(root)[:10]:
        print(f'{i["id"]:32} {i.get("status", "open"):9} {str(i.get("words", ""))[:60]}')
    return 0
