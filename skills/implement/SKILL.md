---
name: implement
description: Stage 5 of the development pipeline. Implement one task from tasks.md against the approved design, with test files locked. Use after acceptance tests are approved; start a fresh session per task.
argument-hint: <feature-name> [task-number]
arguments: [feature, task]
---

# Stage 5: implement task $task of `$feature`

Inputs: approved `design.md`, `tasks.md`, and the approved tests.

## 1. Lock the tests

```bash
mkdir -p .groundwork/state && touch .groundwork/state/tests-locked
```

While the lock exists, the plugin's hook denies edits to test files. Only
the user removes it. If a test looks wrong, stop and tell the user what is
wrong and why; do not work around it.

## 2. Implement

- Do only task $task (the first unchecked task if none was given).
- Follow the design. If the design turns out to be wrong, stop and say so;
  changing the design is the user's decision.
- Reuse what research.md lists. Before adding a helper, search for an
  existing one.
- Commit in small steps. The plugin runs the project's checks when you
  commit and blocks the commit if they fail. Fix what they report at the
  cause. Do not add suppressions, skips or lowered thresholds.

## 3. Finish the task

- Run the tagged tests for the criteria this task covers and show the
  output.
- Tick the task in tasks.md.
- Commit with a message that names the task and criteria.
- Tell the user the task is done and that the next task should start in a
  fresh session (`/clear`). When all tasks are done, the next step is
  `/dev-groundwork:review $feature`, and the user removes the lock with
  `! rm .groundwork/state/tests-locked` once review passes.
