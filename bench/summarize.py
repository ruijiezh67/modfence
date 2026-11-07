"""Markdown tables from a feature_bench results file.

python bench/summarize.py RESULTS.jsonl [--exclude "EXAMPLE:CHECK NAME" ...]
--exclude drops a check found to be wrong after the run (it is listed in the output, never silently)."""
import json, statistics as st, sys
from collections import defaultdict

CONDS = ["vibe", "fence-all", "fence-chain", "fence-all-tests"]


def ms(xs, fmt):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "N/A"
    return fmt.format(st.mean(xs)) + (" ± " + fmt.format(st.stdev(xs)) if len(xs) > 1 else "")


def main(path, exclude=()):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    for r in rows:
        if "acceptance" in r:
            r["acceptance"] = [a for a in r["acceptance"] if f"{r['example']}:{a[0]}" not in exclude]
            r["acceptance_passed"] = sum(1 for a in r["acceptance"] if a[1])
            r["acceptance_total"] = len(r["acceptance"])
    for e in exclude:
        print(f"Excluded check: {e}")
    crashed = [r for r in rows if "crash" in r]
    rows = [r for r in rows if "crash" not in r]
    print(f"{len(rows)} attempts, {len(crashed)} crashed\n")
    print("| Condition | Attempts | Acceptance checks passed | Features fully correct | Project tests pass | Runs | Cost per feature | Turns | Output tokens | Edits outside fence |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for c in CONDS:
        r = [x for x in rows if x["condition"] == c]
        if not r:
            continue
        acc = sum(x["acceptance_passed"] for x in r), sum(x["acceptance_total"] for x in r)
        full = sum(x["acceptance_passed"] == x["acceptance_total"] for x in r)
        out = "N/A" if c == "vibe" else str(sum(len(x["outside_fence"] or []) for x in r))
        print(f"| {c} | {len(r)} | {acc[0]}/{acc[1]} | {full}/{len(r)} | {sum(bool(x['tests_ok']) for x in r)}/{len(r)} "
              f"| {ms([x['runs'] for x in r], '{:.1f}')} | {ms([x['cost_usd'] for x in r], '${:.2f}')} "
              f"| {ms([x['turns'] for x in r], '{:.1f}')} | {ms([x['tokens']['output_tokens'] for x in r], '{:,.0f}')} | {out} |")
    print("\nPer task (acceptance passed / total, cost):\n")
    by = defaultdict(dict)
    for x in rows:
        by[x["example"]].setdefault(x["condition"], []).append(x)
    print("| Task | " + " | ".join(CONDS) + " |")
    print("|---|" + "---|" * len(CONDS))
    for ex in sorted(by):
        cells = []
        for c in CONDS:
            r = sorted(by[ex].get(c, []), key=lambda x: x["rep"])
            cells.append(", ".join(f"{x['acceptance_passed']}/{x['acceptance_total']} ${x['cost_usd']:.2f}" if x["cost_usd"] is not None
                                   else f"{x['acceptance_passed']}/{x['acceptance_total']} N/A" for x in r) or "N/A")
        print(f"| {ex} | " + " | ".join(cells) + " |")
    fails = defaultdict(int)
    for x in rows:
        for name, ok, _ in x["acceptance"]:
            if not ok:
                fails[(x["example"], name)] += 1
    if fails:
        print("\nFailed checks (count over all attempts):\n")
        for (ex, name), n in sorted(fails.items()):
            print(f"- {ex}: {name} ({n})")


if __name__ == "__main__":
    args = sys.argv[1:]
    excl = [args[i + 1] for i, a in enumerate(args) if a == "--exclude"]
    main(args[0], excl)
