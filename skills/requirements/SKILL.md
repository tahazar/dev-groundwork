---
name: requirements
description: Stage 1 of the development pipeline. Interview the user and write requirements.md with numbered EARS acceptance criteria for a feature. Use when starting a new feature or a change larger than one sentence.
argument-hint: <feature-name> [brief description]
arguments: [feature]
---

# Stage 1: requirements for `$feature`

Output: `<specDir>/$feature/requirements.md`, from
`${CLAUDE_PLUGIN_ROOT}/templates/spec/requirements.md`. Read `specDir` from
`.groundwork/config.json`; if the file is missing, ask the user to run
`/dev-groundwork:setup` first.

`$feature` is a short kebab-case name. It appears in test tags, so keep it
stable.

## 1. Read before asking

Read the request ($ARGUMENTS), the project's CLAUDE.md, and the code the
feature touches. Do not ask what the code already answers.

## 2. Interview

Use the AskUserQuestion tool. Ask about the hard parts, not the obvious
ones: edge cases, failure behavior, what happens to existing data or users,
limits, and what is out of scope. Keep going until each criterion below
could be tested without asking the user again.

## 3. Write the criteria

- One EARS sentence per criterion, with an ID: `- **AC-1** When ...`.
- Each criterion is observable from outside the code: an output, a state
  change, an error message, a timing. "Uses a cache" is a design choice,
  not a criterion; "returns within 50 ms on a repeat call" is a criterion.
- Include at least one criterion for bad input or failure (EARS "If ...,
  then ...").
- Put anything the user does not want built under "Out of scope".
- Questions you could not resolve go under "Open questions" with an owner.
  Do not guess an answer.

## 4. Gate

Show the user the criteria and ask for approval. On approval, set
`- Status: approved (<date>, by <user>)`. Do not start research until the
criteria are approved.
