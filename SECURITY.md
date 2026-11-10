# Security

## What modfence does and does not do

- The server binds to `127.0.0.1` only. Requests must carry a localhost `Host` header, and every request that changes something must carry an `X-Modfence` header, so another website cannot drive it from your browser.
- modfence has no telemetry and sends nothing anywhere by itself. Your code reaches a model only through runs of your own Claude Code CLI, which you start from the UI.
- It writes only inside the project it opens: `<project>/.modfence/` (git-ignored), the files a run changes, `.claude/settings.local.json` while a fence is set (removed when the fence is cleared or the server exits), and `.claude/skills/<name>/` when you add a skill.
- **Skills are third-party instructions.** A skill added from *Skills for this project* is downloaded as text; modfence never runs it, but Claude Code will follow it in that project. Read it before you add it.
- **The fence is a guard, not a sandbox.** The hook blocks the agent's file tools outside the fence; a shell command can still write elsewhere. modfence reports such changes after the run and offers a revert. Do not rely on it to contain an agent you do not trust.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting on this repository (Security tab, *Report a vulnerability*), or email ruijiezh@umich.edu. You will get an answer within a week.
