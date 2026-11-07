# Engineering standards: what modfence follows, and how to check it

modfence is meant to make AI-assisted coding meet the bar that experienced engineers already hold for human changes. This page lists the rules it takes from published practice, whether modfence does each one today, and the command or test that shows it. "Not yet" means not built; nothing here is claimed without a check.

Sources (short names used below):
- **git**: git/git `Documentation/SubmittingPatches` and `CodingGuidelines`.
- **Google**: Google Engineering Practices, "Small CLs" and "What to look for in a code review".
- **Anthropic**: "Best practices for Claude Code" (plan first; give the agent a pass/fail check; "if something has to happen every time, make it a hook").
- **Beck**: Kent Beck, Tidy First (do not mix structural and behavioral changes).
- **Willison**: Simon Willison on vibe engineering ("I won't commit any code to my repository if I couldn't explain exactly what it does to somebody else").
- **Pocock**: Matt Pocock's agent skills `grilling` (questions in rounds, each with a recommended answer) and `tdd`.

## The rules for a change made by an agent

| # | Rule | Source | modfence today | How to check |
|---|---|---|---|---|
| 1 | Plan before editing: settle open questions, name what will change, agree on "done". | Anthropic, Pocock | **Yes.** Every edit run starts with a read-only plan: at most 4 questions with a recommended answer, the functions to touch, and a done line. Build resumes the same session. | `test_plan_phase_reads_only_and_returns_a_plan` |
| 2 | Every change has a pass/fail check, and the harness enforces it, not the prompt. | Anthropic, git | **Yes.** A `Stop` hook runs the project's tests (pytest or unittest, or `--test-cmd`) and sends the agent back once if they fail. | `test_build_phase_adds_the_done_check_hook`, `test_done_check_blocks_once_then_lets_the_agent_stop` |
| 3 | The agent may only change what you agreed to; anything else is blocked or reported. | Anthropic ("make it a hook") | **Yes** for file tools: a `PreToolUse` hook denies edits outside the fence and fails closed. Shell writes are reported after the run, with a revert. | `test_hook_denies_outside_and_allows_inside_and_reads`, `test_hook_fails_closed`, `test_read_only_run_may_edit_nothing` |
| 4 | You can explain every change you keep. | Willison | **Partly.** Each run lists the functions added, changed and removed, with one line on what each does now; the diff is one click away. There is no walkthrough or quiz yet. | History view; `test_changes_are_named_per_function` |
| 5 | Every change can be undone. | git (small reversible commits) | **Yes.** Each run is a numbered version in History with a revert; a file edited again since is left alone. | `test_run_is_stored_with_diff_and_can_be_reverted`, `test_revert_leaves_files_edited_after_the_run`, `test_versions_keep_prompt_and_revert` |
| 6 | One logical change per run; about 100 changed lines is a good size, 1000 is too big. | git, Google | **Shown, not enforced.** History shows functions and files per version. No size warning yet. | History view |
| 7 | Do not mix structural changes (renames, moves) with behavior changes. | Beck | **Not yet.** | N/A |
| 8 | Test first: a failing test before the fix. | Pocock (`tdd`), Beck | **Not yet** as a mode. You can ask for it in the instruction. | N/A |
| 9 | A commit message written from the run, edited by a human. | git | **Not yet.** | N/A |

## The rules for modfence's own code

| Rule | Source | Status | How to check |
|---|---|---|---|
| Tests come with every change, and the suite passes before a commit. | git | Yes: 27 deterministic tests, no model or network. | `python -m unittest discover -s tests -t .` |
| No whitespace errors. | git | Yes. | `git diff --check` |
| One logical change per commit, subject 50 characters or less. | git | Since 2026-11-06; two older subjects are longer (74 and 63). | `git log --format=%s` |
| Standard library only; nothing installed outside the project. | (project rule) | Yes: `dependencies = []` in `pyproject.toml`. | `pip install .` in a fresh venv, then `modfence --help` |
| Local server cannot be driven by another website. | OWASP (CSRF, DNS rebinding) | Yes: `Host` must be localhost; writes need the `X-Modfence` header. | `test_guards` |
| CI runs the tests on every push. | git | **Not yet**: the workflow is ready on branch `ci`, waiting for a token with the `workflow` scope. | N/A |

## What is measured, and what is not

- Fence compliance and cost against plain Claude Code: [EVALUATION.md](EVALUATION.md), 4 tasks x 2 runs. Suggestive, not conclusive.
- Plan + build against a fenced run without a plan: one run each, so N/A as a comparison.
- Whether people understand their project better with modfence: not measured. N/A.
