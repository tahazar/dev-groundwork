---
name: design
description: Stage 3 of the development pipeline. Write at least two structurally different designs, compare them, choose one, have it reviewed in a fresh context, and break it into tasks. Use after research.md passes its checks.
argument-hint: <feature-name>
arguments: [feature]
---

# Stage 3: design for `$feature`

Inputs: approved `requirements.md`, checked `research.md`, and
`.groundwork/project-rules.md`.
Outputs: `<specDir>/$feature/design.md` and `tasks.md`, from the templates in
`${CLAUDE_PLUGIN_ROOT}/templates/spec/`.

Work in plan mode until the design is approved; nothing in this stage edits
source code.

## 1. Generate options

Write at least two options that differ in structure: where the code lives,
what owns the data, how parts communicate, what is reused versus added.
Two variations of one idea do not count. One option should be the
smallest change that meets every criterion, built mostly from what
research found.

For each option, argue it at its strongest. A strawman alternative defeats
the point of comparing.

## 2. Compare and choose

Fill in the comparison table. Judge interfaces first by how much work they
leave to callers, then by implementation size and risk. Every factual
claim cites a C-id from research.md.

Choose, and record why the others lost under "Rejected options".

## 3. Check the chosen design

- Every criterion maps to part of the design ("Criteria coverage").
- Every project rule the design touches is addressed ("Project rules
  check"). An exception needs a reason.
- Every reuse claim names real code: confirm each path and symbol exists.

## 4. Review in a fresh context

Run the `design-reviewer` agent. Give it the paths to requirements.md,
research.md, design.md and the project rules file, nothing else, so it
judges the documents rather than this conversation.

Fix each blocking finding, or explain to the user why it is wrong. Re-run
the review after substantial changes. Treat non-blocking findings as
optional.

## 5. Tasks

Write `tasks.md`: small tasks in dependency order, each naming the criteria
it moves toward passing. A task should be reviewable in one sitting.

## 6. Gate

Show the user the decision, the rejected options and the review result.
On approval, set `- Status: approved (<date>, by <user>)` in design.md.
