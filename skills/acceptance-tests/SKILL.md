---
name: acceptance-tests
description: Stage 4 of the development pipeline. Write failing tests tagged with acceptance-criterion IDs before any implementation. Use after the design is approved, or as the first step of a bug fix.
argument-hint: <feature-name>
arguments: [feature]
---

# Stage 4: acceptance tests for `$feature`

Inputs: approved `requirements.md` and `design.md`.
Output: tests in the project's usual test locations, each tagged
`[$feature AC-n]` in its name or in a comment on the same line.

## Rules

- Test behavior the criteria describe, through the interfaces the design
  defines. Do not test private details the design leaves open.
- Use real code. Fake process boundaries (network, filesystem, devices,
  time) the way the project already does; never mock the unit under test.
- Each failure criterion ("If ..., then ...") gets a test that drives the
  failure and checks the specific error, not just that something threw.
- Where inputs vary, prefer a property-based test or a table of cases over
  one example, so hard-coding a visible case cannot pass.
- Detectors and classifiers get a negative case: input that must not
  trigger them.

## Steps

1. Write the tests. Stub only enough of the new interface for them to load
   (empty functions, types), so they fail on behavior, not on imports.
2. Run them and confirm each fails for the expected reason. Keep the
   output.
3. Check coverage of the criteria:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_ac_coverage.py $feature
   ```

4. Commit the tests on their own, so the review can see them separately
   from the code.

## Gate

Show the user the tests, the failing output and the coverage report. The
user reviews the tests: they are the definition of done for the
implementation, so a wrong test here becomes wrong code later. Do not start
implementation until the user approves.
