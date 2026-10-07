---
name: debug
description: Find the root cause of a bug, failing test or red CI check before changing any code, then hand the fix to test-first. Use whenever something fails or behaves unexpectedly, including after a fix attempt did not work.
argument-hint: <symptom or failing check>
arguments: [symptom]
---

# Debug: `$symptom`

No fix before a root cause. A change made to see whether the error goes
away is a guess, and a guess that happens to pass hides the real cause.

## 1. Read and reproduce

- Read the whole error: message, stack trace, file and line, exit code.
  For a CI failure, read the job log, not just the check's title.
- Reproduce it locally with one command and keep the output. If it does not
  reproduce, find out what differs (environment, versions, data, order of
  tests) before going further. "Flaky" is a symptom, not a cause.
- Check whether the base branch fails the same way. If it does, the cause
  is not in this change; say so and find the change that introduced it.

## 2. Trace to the origin

- Look at what changed: `git log` and `git diff` against the last known
  good state.
- Follow the bad value backwards from where it fails to where it is first
  wrong. Fix it there, not where it surfaces.
- Across a boundary (process, network, CI step, subprocess), check what
  goes in and what comes out of each side before deciding which side is
  wrong.
- Find working code that does the same thing and list every difference.

## 3. One hypothesis at a time

- Write the hypothesis down: "X fails because Y, as shown by Z."
- Test it with the smallest change or measurement that can prove it wrong.
  Change one thing at a time.
- If it was wrong, undo the change before forming the next hypothesis. Do
  not stack attempts.
- If you do not understand something, say so and look it up; do not paper
  over it.

## 4. Fix through test-first

Once the cause is confirmed, run `/dev-groundwork:test-first` with a test
that reproduces the symptom. The fix goes at the origin found in step 2.

A timing problem is fixed by waiting for the condition that matters, not by
a longer sleep. If no signal exists, the delay says what it waits for and
why there is no signal.

## 5. Stop after three failed fixes

If three fixes have not worked, stop. Repeated fixes that each move the
problem somewhere else point to a design problem, and changing the design
is the user's decision. Report what you tried and what each attempt showed.

## Output

A short root-cause note for the commit message or pull request: the
symptom, the cause, the evidence that confirmed it, and where the fix is.
