# dev-groundwork

A Claude Code plugin that runs features through a gated pipeline:
requirements, research, design, acceptance tests, implementation, review.
Each stage produces one document or change and has one gate before the next
stage starts. Scripts and hooks enforce the parts that should never depend
on an agent remembering an instruction.

See [docs/pipeline.md](docs/pipeline.md) for the stages, the reasoning behind
each one, and the sources.

## Install

In Claude Code:

```
/plugin marketplace add tahazar/dev-groundwork
/plugin install dev-groundwork@dev-groundwork
```

Then, in each project that should use it:

```
/dev-groundwork:setup
```

The plugin's hooks do nothing in a project until setup has written
`.groundwork/config.json`, so installing it globally is safe.

## Stages

| Command | Produces |
|---|---|
| `/dev-groundwork:requirements <feature>` | `requirements.md`: EARS acceptance criteria `AC-1`, `AC-2`, ... approved by you |
| `/dev-groundwork:research <feature>` | `research.md`: code to reuse and checked citations for external APIs |
| `/dev-groundwork:design <feature>` | `design.md` with two or more options, a decision and a fresh-context review, plus `tasks.md` |
| `/dev-groundwork:acceptance-tests <feature>` | Failing tests tagged `[<feature> AC-n]` |
| `/dev-groundwork:implement <feature> [task]` | One task, with test files locked |
| `/dev-groundwork:review <feature> [base]` | Mechanical checks plus a fresh-context code review |

Skip the first three for a change you can describe in one sentence.

Outside the stages:

| Command | Use |
|---|---|
| `/dev-groundwork:test-first <change>` | A small change or bug fix, red-green-refactor, with the test shown failing without the change |
| `/dev-groundwork:debug <symptom>` | A failure or bug: root cause first, one hypothesis at a time, then test-first |

## What enforces what

| Mechanism | Enforces |
|---|---|
| `PreToolUse` hook | While `.groundwork/state/tests-locked` exists, edits to test files are denied, and only you can remove the lock |
| `PreToolUse` hook on `git commit` | The project's checks (`onCommit`: format, lint, typecheck, tests) pass before Claude commits code; a failure blocks the commit |
| `check_citations.py` | Each cited quote appears at its source, the source's domain supports the claimed tier, and Tier 3 sources are only pointers |
| `check_ac_coverage.py` | Every approved acceptance criterion has a tagged test, and no test cites a criterion that does not exist |
| `detect_workarounds.py` | No new test skips, lint or type suppressions, coverage exclusions, threshold edits or deleted tests without a `groundwork-allow: <reason>` (a re-based threshold carries the reason on its new line, which also covers the old one) |
| `design-reviewer` agent | Real alternatives, every criterion met, reuse claims true, project rules followed |
| `code-reviewer` agent | No gamed tests, criteria tests that can fail, design followed, no duplicated code |
| `citation-verifier` agent | Each quote supports its claim |

Setup copies the three check scripts into the project's `.groundwork/bin/`
and adds a GitHub Actions workflow that runs them on pull requests, so CI
does not need the plugin installed.

## Limits

- The test lock is a guardrail, not a security boundary. A command the hook
  does not recognize can still change a test file; the review stage and
  `detect_workarounds.py` exist to catch that.
- `check_citations.py` reads HTML and plain text. PDFs and pages rendered by
  JavaScript need a manual check recorded with `override: <reason>`, and
  every override is listed in the report.
- The commit check runs on the working tree, not the staged snapshot, so
  it can pass on changes that are not all in the commit. CI checks the
  commit itself.
- Checks run at the commit, not after every edit. Mid-change code is often
  half-finished, and checking every intermediate state pushes the agent to
  silence warnings that would have resolved on their own. With small,
  frequent commits the gate still runs often.
- Cloud sessions do not load plugins from repository settings, so there
  the hooks do not run and CI is the only gate.
- `detect_workarounds.py` reads `git diff`, so it does not see untracked
  files. Commit or stage new files before running it locally; CI always
  sees them.
- The scripts need Python 3.10 or later and git. They use only the standard
  library.

## Development

```sh
python3 -m unittest discover tests
ruff check . && ruff format --check .
claude plugin validate --strict .claude-plugin/plugin.json
```
