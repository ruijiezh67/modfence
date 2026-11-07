"""Black-box acceptance checks for the cross-module tasks used by the benchmark.

Each check is one bullet of the task's "Acceptance" list in the example's TASKS.md, run through the project's
own CLI (or, for tinygpt, a short Python snippet) in a subprocess, so the check does not depend on how the
agent named things inside the modules. check(example, root, pristine) -> list of (bullet, passed, detail).
`pristine` is an untouched copy of the example, used where a bullet compares against the old behavior.
"""
import json, os, re, subprocess, sys, tempfile
from datetime import date, timedelta

PY = sys.executable


def _run(root, args, stdin=None, timeout=120):
    p = subprocess.run([PY, *args], cwd=root, input=stdin, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def calculator(root, pristine):
    out = []
    for expr, want in (("2 ^ 3", "8"), ("2 ^ 3 ^ 2", "512"), ("-2 ^ 2", "-4"), ("2 * 3 ^ 2", "18")):
        code, so, se = _run(root, ["-m", "calc", expr])
        out.append((f"{expr} prints {want}", code == 0 and so == want, f"exit {code}, out {so!r} {se[-120:]!r}"))
    code, so, se = _run(root, ["-m", "calc", "0 ^ -1"])
    msg = so + se  # the error must come from the new operator, not from the lexer not knowing '^'
    out.append(("0 ^ -1 exits 1 with an error", code == 1 and bool(msg) and "unexpected character" not in msg, f"exit {code}, {so!r} {se[-120:]!r}"))
    return out


def library(root, pristine):
    out, tmp = [], tempfile.mkdtemp()
    data = os.path.join(tmp, "lib.json")
    day0 = date(2026, 1, 5)

    def cli(base, *args, today=day0, f=data):
        return _run(base, ["-m", "library", "--data", f, "--today", today.isoformat(), *args])

    def lend(member, today=day0):
        code, so, se = cli(root, "lend", "111", member, today=today)
        m = re.search(r"loan (\d+): due (\S+)", so)
        return (int(m.group(1)), date.fromisoformat(m.group(2))) if code == 0 and m else (None, None)

    cli(root, "add-book", "111", "Dune", "Herbert", "--copies", "9")
    for mid in ("m1", "m2"):
        cli(root, "add-member", mid, mid.upper())
    for days, fine in ((10, "2.50"), (100, "10.00"), (0, "0.00")):
        lid, due = lend("m1")
        code, so, se = cli(root, "return", str(lid), today=due + timedelta(days=days)) if lid else (None, "", "lend failed")
        out.append((f"return {days} days late prints fine {fine}", code == 0 and f"loan {lid} returned, fine {fine}" in so,
                    f"{so!r} {se[-120:]!r}"))
    ids = []
    for _ in range(2):
        lid, due = lend("m2")
        if lid:
            cli(root, "return", str(lid), today=due + timedelta(days=10))
            ids.append(lid)
    code, so, se = cli(root, "lend", "111", "m2")
    blocked = len(ids) == 2 and code != 0 and bool(se or so)
    out.append(("two unpaid 2.50 fines block lending", blocked, f"exit {code} {se[-160:]!r}"))
    for lid in ids:
        cli(root, "pay", str(lid))
    code, so, se = cli(root, "lend", "111", "m2")
    out.append(("after paying both, lending works", blocked and code == 0, f"blocked first: {blocked}, exit {code} {so!r} {se[-120:]!r}"))
    old = os.path.join(tmp, "old.json")  # written by the unchanged code: no fine field anywhere
    cli(pristine, "add-book", "222", "Emma", "Austen", f=old)
    cli(pristine, "add-member", "m9", "M9", f=old)
    _, so, _ = cli(pristine, "lend", "222", "m9", f=old)
    m = re.search(r"loan (\d+): due (\S+)", so)
    code, so2, se2 = cli(root, "return", m.group(1), today=date.fromisoformat(m.group(2)), f=old) if m else (None, "", "")
    out.append(("an old JSON file loads (fine 0)", code == 0 and "fine 0.00" in so2, f"exit {code} {so2!r} {se2[-160:]!r}"))
    return out


def spreadsheet(root, pristine):
    out = []

    def repl(lines):
        code, so, se = _run(root, ["-m", "sheet"], stdin="\n".join(lines) + "\n")
        return [t.strip() for chunk in so.split("sheet>") for t in chunk.splitlines() if t.strip()], se

    res, se = repl(["set A1 hello", "get A1"])
    out.append(("get A1 prints hello", res[-1:] == ["hello"], f"{res} {se[-120:]!r}"))
    res, se = repl(["set A1 hello", 'set B1 =CONCAT(A1, " world")', "get B1"])
    out.append(("CONCAT gives hello world", res[-1:] == ["hello world"], f"{res} {se[-120:]!r}"))
    res, se = repl(["set A1 hello", "set C1 =A1+1", "get C1"])
    out.append(("text + 1 is #VALUE!", res[-1:] == ["#VALUE!"], f"{res} {se[-120:]!r}"))
    res, se = repl(["set A1 hello", "set A2 4", "set A3 6", "set B1 =SUM(A1:A3)", "set B2 =AVG(A1:A3)", "get A1", "get B1", "get B2"])
    out.append(("SUM and AVG ignore text", res[-3:] == ["hello", "10", "5"], f"{res} {se[-120:]!r}"))  # A1 must really hold text
    f = os.path.join(tempfile.mkdtemp(), "t.csv").replace("\\", "/")
    res1, _ = repl(['set A1 hello, "quoted"', f"export {f}"])
    res2, se = repl([f"import {f}", "get A1"])
    out.append(("CSV round trip keeps text", res2[-1:] == ['hello, "quoted"'], f"{res1} {res2} {se[-120:]!r}"))
    return out


TINYGPT_SNIPPET = r'''
import json, sys, torch
import tinygpt.train.loop as loop
import tinygpt.data.batches as batches
from tinygpt.config.settings import ModelConfig, TrainConfig
from tinygpt.data.batches import to_tensor
from tinygpt.data.tokenizer import CharTokenizer
from tinygpt.model.gpt import GPT

text = "abcd" * 64
tok = CharTokenizer(text)
data = to_tensor(tok, text)
mcfg = ModelConfig(vocab_size=tok.vocab_size, block_size=8, n_layer=1, n_head=2, n_embd=16)

def fresh():
    torch.manual_seed(0)
    return GPT(mcfg)

def run(steps, **kw):
    cfg = TrainConfig(steps=steps, batch_size=8, lr=1e-2, **kw)
    m = fresh()
    return m, loop.train(m, data, mcfg, cfg)

mode = sys.argv[1]
out = {}
if mode == "baseline":
    out["losses"] = run(6)[1]
else:
    out["losses"] = run(6, grad_accum=1, grad_clip=None)[1]
    calls = [0]
    real = batches.get_batch
    def counting(*a, **k):
        calls[0] += 1
        return real(*a, **k)
    loop.get_batch = batches.get_batch = counting
    out["accum_len"] = len(run(5, grad_accum=4)[1])
    out["accum_calls"] = calls[0]
    loop.get_batch = batches.get_batch = real
    def moved(clip):
        m0 = fresh(); start = [p.detach().clone() for p in m0.parameters()]
        m, _ = run(5, grad_clip=clip)
        return sum((p.detach() - s).abs().sum().item() for p, s in zip(m.parameters(), start))
    out["moved_clip"], out["moved_free"] = moved(1e-9), moved(None)
    l = run(120, grad_accum=2)[1]
    out["overfit"] = sum(l[-10:]) / 10 < 0.3 * l[0]
print("JSON" + json.dumps(out))
'''


def tinygpt(root, pristine):
    def snippet(base, mode):
        code, so, se = _run(base, ["-c", TINYGPT_SNIPPET, mode], timeout=300)
        m = re.search(r"JSON(.*)$", so, re.M)
        return (json.loads(m.group(1)) if m else None), f"exit {code} {se[-200:]!r}"
    base, _ = snippet(pristine, "baseline")
    got, why = snippet(root, "new")
    if not got:
        return [(b, False, why) for b in ("accum=1, clip=None keeps losses", "accum=4 returns steps losses, 4x batches",
                                          "tiny clip barely moves params", "overfits with accum=2")]
    same = base and len(base["losses"]) == len(got["losses"]) and all(abs(a - b) < 1e-5 for a, b in zip(base["losses"], got["losses"]))
    return [
        ("accum=1, clip=None keeps losses", bool(same), f"{base and base['losses'][:3]} vs {got['losses'][:3]}"),
        ("accum=4 returns steps losses, 4x batches", got["accum_len"] == 5 and got["accum_calls"] == 20,
         f"len {got['accum_len']}, batches {got['accum_calls']}"),
        ("tiny clip barely moves params", got["moved_clip"] < 0.1 * got["moved_free"], f"{got['moved_clip']:.4g} vs {got['moved_free']:.4g}"),
        ("overfits with accum=2", got["overfit"], ""),
    ]


CHECKS = {"01-calculator": calculator, "02-library": library, "03-spreadsheet": spreadsheet, "04-tinygpt": tinygpt}


def check(example, root, pristine):
    try:
        return CHECKS[example](root, pristine)
    except Exception as e:  # a crash in a check counts as failing that whole task, and is recorded
        return [("acceptance crashed", False, repr(e)[:300])]


if __name__ == "__main__":  # python bench/acceptance.py EXAMPLE ROOT: print the checks for one project
    ex, root = sys.argv[1], sys.argv[2]
    pristine = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", ex)
    for name, ok, detail in check(ex, root, pristine):
        print("PASS" if ok else "FAIL", name, "" if ok else detail)
