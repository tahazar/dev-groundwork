---
name: test-first
description: Make a small change or bug fix test-first, red-green-refactor, and prove the test guards the change. Use for changes that skip stages 1 to 3 (describable in one sentence) and for every bug fix after debug has found the cause.
argument-hint: <change or bug>
arguments: [change]
---

# Test first: `$change`

A test you never saw fail proves nothing: it may pass because it tests the
wrong thing. Every step below keeps its command output.

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
- Run the test, then the project's full checks (the `onCommit` command in
  `.groundwork/config.json`). A failure anywhere is yours to fix or to
  report by name, even if this change did not cause it.

## 3. Refactor

Clean up names and duplication with every check still green. No new
behavior in this step.

## 4. Prove the test guards the change

Remove the code change while keeping the test (for example
`git stash push -- <changed source files>`), run the test and confirm it
fails, then restore the change and confirm it passes. Keep both outputs. A
test that still passes without the change does not guard it.

## 5. Commit

Commit the test with the change, or the test first when the project wants
them separate. The message says what the test pins and, for a bug, the
root cause from `/dev-groundwork:debug`.
