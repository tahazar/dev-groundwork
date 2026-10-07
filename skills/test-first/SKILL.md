---
name: test-first
description: Make a small change or bug fix test-first, red-green-refactor, and prove the test guards the change. Use for changes that skip stages 1 to 3 (describable in one sentence) and for every bug fix after debug has found the cause.
argument-hint: <change or bug>
arguments: [change]
---

# Test first: `$change`

A test you never saw fail proves nothing: it may pass because it tests the
wrong thing. Every step below keeps its command output.

While tests are locked (`.groundwork/state/tests-locked` exists), do not
write or edit tests: the approved failing test is the red step, so start at
step 2. If a new test is needed, stop and tell the user.

## 1. Red

- Write one test for the behavior the change adds or the bug breaks. For a
  bug, the test reproduces the reported symptom, not an internal detail.
- Use real code. Fake process boundaries the way the project already does;
  never mock the unit under test.
- Run it. It must fail, and fail for the expected reason: the behavior is
  missing or wrong, not an import error or a typo. If it passes, it does
  not test the change; rewrite it.

## 2. Green

- Write the least code that makes the test pass. No options, layers or
  clean-ups the test does not need.
- Run the test, then the project's full checks: the `onCommit` command in
  `.groundwork/config.json`, or, if it is unset, the format, lint,
  typecheck and test commands the project documents. A failure anywhere
  is yours to fix or to report by name, even if this change did not cause
  it.

## 3. Refactor

Clean up names and duplication with every check still green. No new
behavior in this step.

## 4. Prove the test guards the change

Take the code change out, keep the test, and watch the test fail; then put
the change back and watch it pass. Name only source files, never tests:

```bash
git add -N <new source files>       # so the diff includes new files
patch=$(mktemp)
git diff -- <changed source files> > "$patch"
test -s "$patch"                    # an empty patch means a wrong file list: stop
git apply -R "$patch"               # run the test: it must fail
git apply "$patch"                  # run the test: it must pass
```

Keep both outputs. A test that still passes without the change does not
guard it. Do not use `git stash` for this: with nothing to stash it saves
nothing, and the restore then applies an older, unrelated stash.

## 5. Commit

Commit the test with the change, or the test first when the project wants
them separate. The message says what the test pins and, for a bug, the
root cause from `/dev-groundwork:debug`.
