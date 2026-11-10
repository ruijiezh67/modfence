"""Can a model read the brief? A cheap comprehension probe of brief.ENCODINGS before any coding run (golden rule 7:
the brief's format is whatever measures best; this probe screens out encodings a model misreads).

For each fence, questions with known answers are generated from brief.facts (deterministic; no model writes them):
  params   "What parameters does <name> take?"        gold: the def's parameter names (only defs shown with a stub)
  users    "Which modules use the fence's <name>?"    gold: the user modules in the contract
  imports  "Does the fence use <name> from <module>?" gold: yes for a used name, no for a distractor (half and half)
The model sees only one encoding of the brief and answers all questions as JSON. Score: exact match, as k/n.
Encodings that drop a fact (iface has no parameters or users) are expected to fail those questions: that is the
price of their size, and the point of measuring it.

Usage: python bench/brief_probe.py OUT.jsonl [--model haiku] [--projects examples,PATH...]
Fences are fixed below so the run is repeatable. Model cost is reported per call (N/A when the CLI gives none).
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from modfence import analyze, brief, purpose, runner  # noqa: E402

EX = os.path.join(os.path.dirname(HERE), "examples")
FENCES = [  # (project root, fence), chosen to cover small and large briefs
    (os.path.join(EX, "01-calculator"), ["calc/evaluator"]),
    (os.path.join(EX, "02-library"), ["library/services"]),
    (os.path.join(EX, "03-spreadsheet"), ["sheet/engine"]),
    (os.path.join(EX, "00-iris"), ["iris/cli"]),
]
SYSTEM = ("You answer questions about a software project using only the brief you are given. Reply with JSON only: "
          '{"answers": {"<question id>": <answer>}}. For a list answer give a JSON list of strings; for yes/no give "yes" '
          'or "no". If the brief does not say, answer "unknown".')


def questions(f):
    """[(id, kind, text, gold)] from brief.facts; deterministic."""
    qs = []
    defs = [d for d in f["deps"] if d["stub"].startswith("def ")]
    for i, d in enumerate(defs[:4]):
        params = [p.strip().lstrip("*") for p in re.search(r"\((.*?)\)", d["stub"]).group(1).split(",") if p.strip()]
        qs.append((f"p{i}", "params", f"List the parameter names of `{d['name']}` from module {d['mod']}, in order.", params))
    for i, c in enumerate(f["contract"][:4]):
        qs.append((f"u{i}", "users", f"Which modules use the fence's `{c['name']}`? Answer with module paths (e.g. pkg/mod), not short ids.", c["mods"]))
    used = sorted({(d["mod"], d["name"]) for d in f["deps"]})
    for i, (m, n) in enumerate(used[:3]):
        qs.append((f"y{i}", "imports", f"Does the fence use `{n}` from {m}?", "yes"))
    fake = ["serialize_all", "Registry", "flush_cache"]
    for i, (m, _) in enumerate(used[:3]):
        qs.append((f"n{i}", "imports", f"Does the fence use `{fake[i]}` from {m}?", "no"))
    return qs


def correct(kind, ans, gold):
    if kind == "imports":
        return str(ans).strip().lower() == gold
    if not isinstance(ans, list):
        return False
    norm = lambda xs: [str(x).strip().lstrip("*") for x in xs]
    return norm(ans) == norm(gold) if kind == "params" else sorted(norm(ans)) == sorted(norm(gold))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--extra", default="", help="more fences as PATH:module,PATH:module")
    a = ap.parse_args()
    fences = FENCES + [(x.rsplit(":", 1)[0], [x.rsplit(":", 1)[1]]) for x in a.extra.split(",") if x]
    claude = runner.find_claude()
    with open(a.out, "a", encoding="utf-8") as out:
        for root, fence in fences:
            f = brief.facts(analyze.analyze(root), fence)
            qs = questions(f)
            if not qs:
                continue
            for enc, render in brief.ENCODINGS.items():
                text = render(f)
                prompt = "BRIEF:\n" + text + "\n\nQUESTIONS:\n" + "\n".join(f"{q}: {t}" for q, _, t, _ in qs)
                try:
                    obj, cost = purpose._ask(claude, prompt, system=SYSTEM, model=a.model)
                    answers, err = obj.get("answers") or {}, None
                except Exception as e:  # recorded, not hidden
                    answers, cost, err = {}, None, str(e)[:200]
                score = {}
                for q, kind, _, gold in qs:
                    k, n = score.get(kind, (0, 0))
                    score[kind] = (k + correct(kind, answers.get(q), gold), n + 1)
                row = {"project": os.path.basename(root), "fence": fence, "encoding": enc, "model": a.model,
                       "brief_chars": len(text), "brief_tokens_est": len(text) // 4, "score": score, "cost_usd": cost,
                       "error": err, "answers": answers, "gold": {q: g for q, _, _, g in qs}}
                out.write(json.dumps(row) + "\n"); out.flush()
                print(row["project"], fence, enc, row["brief_tokens_est"], score, cost, err or "", flush=True)


if __name__ == "__main__":
    main()
