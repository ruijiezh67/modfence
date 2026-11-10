# Contributing to modfence

Thanks for helping. modfence is small on purpose: the standard library only, plain HTML, CSS and JS with no build step, and a test suite that never calls a model.

## Before you change anything

Read [docs/GOLDEN_RULES.md](docs/GOLDEN_RULES.md). Every change serves at least one of the seven rules, and its commit says which. A feature that serves none does not ship. When two rules pull against each other, the earlier one wins, except that rules 4 and 7 (protect working code, show what a round changed) are never traded for tokens.

## Set up

```bash
git clone https://github.com/ruijiezh67/modfence && cd modfence
python -m unittest discover -s tests -t .      # or: python -m pytest -q tests
python -m modfence examples/*                  # the app on the bundled examples
```

`tests/fake_claude.py` stands in for the Claude Code CLI: it emits Claude Code's stream-json events and makes the edits a prompt asks for, so runs, hooks and history are tested without a model.

## Making a change

- **Least code that works.** Reuse what is in the codebase, then the standard library. Mark a deliberate shortcut with a `ponytail:` comment that names its limit.
- **One runnable check per piece of logic.** A focused test in `tests/test_modfence.py`; no network in tests.
- **Measure claims.** A claim about tokens, cost or accuracy needs a script in `bench/` and a write-up in [docs/EVALUATION.md](docs/EVALUATION.md). A number that was not measured is written N/A, never 0. Self-made test data documents how it was generated.
- **UI changes** come with a before and after screenshot in the pull request. Check light and dark themes and a narrow window.
- **Commits** have a subject of at most 50 characters in the imperative ("Add …", "Fix …") and a body that names the golden rule.

## Reporting

- Bugs and ideas: [issues](https://github.com/ruijiezh67/modfence/issues).
- Tried it on a real project? A [field report](https://github.com/ruijiezh67/modfence/issues/new?template=field-report.yml) is the most useful thing you can send.
- Security problems: see [SECURITY.md](SECURITY.md).
