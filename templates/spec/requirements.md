# Requirements: <feature>

- Status: draft | approved (<date>, by <name>)
- Requested by: <who asked, and their words if quoted>

## Problem

<One paragraph: who has the problem, what they do today, what goes wrong.>

## Acceptance criteria

One EARS sentence per criterion. Each one becomes at least one test tagged
`[<feature> AC-n]`. Mark a criterion `(deferred)` to keep it on record
without requiring a test yet.

EARS forms:
- Ubiquitous: The system shall <response>.
- Event: When <trigger>, the system shall <response>.
- State: While <state>, the system shall <response>.
- Unwanted: If <condition>, then the system shall <response>.
- Optional: Where <feature is present>, the system shall <response>.

- **AC-1** When <trigger>, the system shall <response>.
- **AC-2** If <bad input or failure>, then the system shall <response>.

## Out of scope

- <What this feature will not do, so nobody builds it by accident.>

## Open questions

- <Question> (owner: <who answers it>)
