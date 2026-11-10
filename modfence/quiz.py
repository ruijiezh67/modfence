"""modfence quiz: after an agent's round, do you still know what it did? (golden rule 3)

    modfence quiz [PROJECT] [--since REV] [--key]

Up to five multiple-choice questions built from the round's receipt, with no model: which modules it touched, which
function it changed, which module may break, which file it added, how many files it changed. Wrong options come from
the same files and the same map, so guessing does not pass. The score is kept in .modfence/quiz.jsonl with the round
it was about; a falling score says the agent does too much per round. --key prints the questions with their answers.
"""
import argparse, ast, json, os, random, sys, time

from . import analyze, modules, receipt, runner


def questions(root, r, seed):
    """[(question, options, set of right option indexes)] for receipt r of the project at root."""
    rng, out = random.Random(seed), []
    parts = [a["id"] for a in r["areas"]]
    shared = modules.load(root)
    every = [m["name"] for m in shared] if shared else sorted({analyze.module_of(p) for p in analyze.walk(root)})

    def ask(q, right, wrong, multi=False):
        wrong = [w for w in dict.fromkeys(wrong) if w not in right]
        rng.shuffle(wrong)
        right = list(right)[:3]
        opts = right + wrong[:4 - len(right)]  # at most 4 options, at least one of them wrong
        if len(opts) == len(right):
            return
        rng.shuffle(opts)
        out.append((q + (" (pick all that apply)" if multi else ""), opts, {i for i, o in enumerate(opts) if o in right}))

    if parts:
        ask("Which parts of the project did this round change?", parts[:3], every, multi=True)
    funcs = [u for u in r["functions"] if u["status"] in ("added", "changed")]
    if funcs:
        u = rng.choice(funcs)
        try:
            tree = ast.parse(analyze.read_text(os.path.join(root, u["file"])))
            lines = analyze.read_text(os.path.join(root, u["file"])).splitlines()
            others = [f["name"] for f in analyze.functions(tree, lines) if f["name"] not in {x["name"] for x in r["functions"]}]
        except (OSError, SyntaxError):
            others = []
        ask(f"Which of these in {u['file']} did the round {u['status'].replace('changed', 'change').replace('added', 'add')}?", [u["name"]], others)
    if r["used_by"]:
        ask("Which part uses the changed code, so it may break?", [rng.choice(r["used_by"])],
            [m for m in every if m not in r["used_by"] and m not in parts])
    added = [f["path"] for f in r["files"] if f["status"] == "added" and f["path"].endswith(".py")]
    if added:
        ask("Which file did the round add?", [rng.choice(added)],
            [p for p in analyze.walk(root) if p not in added and os.path.dirname(p) == os.path.dirname(added[0])])
    n = len(r["files"])
    ask("How many files did the round change?", [str(n)], [str(x) for x in (n + 1, n + 3, max(1, n - 2), n * 2) if x != n and x > 0])
    return out[:5]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modfence quiz", description="Do you still know what the agent did?")
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--since", default="HEAD")
    ap.add_argument("--key", action="store_true", help="print the questions with their answers, ask nothing")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.project)
    try:
        r = receipt.build(root, a.since)
    except RuntimeError as e:
        print(f"modfence quiz: {e}", file=sys.stderr)
        return 2
    if not r["files"]:
        print(f"modfence quiz: nothing changed since {a.since}.")
        return 0
    seed = receipt._git(root, "rev-parse", a.since).decode().strip() + str(len(r["files"]))
    qs = questions(root, r, seed)
    score = 0
    for k, (q, opts, right) in enumerate(qs, 1):
        print(f"\n{k}. {q}")
        for i, o in enumerate(opts):
            print(f"   {'abcd'[i]}) {o}")
        if a.key:
            print("   answer: " + ", ".join("abcd"[i] for i in sorted(right)))
            continue
        got = {"abcd".index(c) for c in input("   your answer: ").strip().lower().replace(",", "") if c in "abcd"[:len(opts)]}
        score += got == right
        print("   right" if got == right else "   the answer: " + ", ".join("abcd"[i] for i in sorted(right)))
    if a.key:
        return 0
    log = os.path.join(runner.state_dir(root), "quiz.jsonl")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.time(), "since": a.since, "files": len(r["files"]), "score": score, "of": len(qs)}) + "\n")
    past = [json.loads(line) for line in open(log, encoding="utf-8")][-5:]
    print(f"\n{score}/{len(qs)}. Last rounds: " + "  ".join(f"{p['score']}/{p['of']} ({p['files']} files)" for p in past))
    return 0
