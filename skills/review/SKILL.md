---
name: review
description: Stage 6 of the development pipeline. Review a feature's diff in a fresh context against its acceptance criteria, design and project rules, and run the mechanical checks for test-gaming workarounds. Use when implementation is complete, before opening or merging a pull request.
argument-hint: <feature-name> [base-ref]
arguments: [feature, base]
---

# Stage 6: review `$feature`

Base ref: `$base`, or the repository's default branch (`origin/main`) if
none was given.

## 1. Mechanical checks

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect_workarounds.py --base <base>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_ac_coverage.py $feature
```

Run the project's full checks too (the `onCommit` command in
`.groundwork/config.json`). Each failure is blocking.

## 2. Fresh-context review

Run the `code-reviewer` agent. Give it:

- the base ref, so it reads the diff itself;
- the paths to requirements.md, design.md and `.groundwork/project-rules.md`;
- the project's review guide if it has one (for example `REVIEW.md`).

Do not give it this conversation or your reasoning about the change.

## 3. Act on findings

- Fix blocking findings at the cause and re-run the checks.
- For a finding you believe is wrong, tell the user why instead of
  changing code to silence it.
- List non-blocking findings for the user; fix only the clearly correct
  ones.

## 4. Gate

Report: check results, each blocking finding and what was done, and any
`groundwork-allow` reasons the workaround check printed. When everything
passes, tell the user they can remove the test lock
(`! rm .groundwork/state/tests-locked`) and open or merge the pull request.
