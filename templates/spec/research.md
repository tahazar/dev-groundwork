# Research: <feature>

- Requirements: `requirements.md` (approved <date>)

## Existing code to reuse

What the codebase already has that this feature should use or extend
instead of rebuilding. Cite each item with a `file:` source.

| What | Where | Use it for |
|---|---|---|
| <helper, module or pattern> | `<path>` | <how the design uses it> |

## External APIs and libraries

For each API that is unfamiliar, rarely used or version-sensitive: the
official documentation for the version in use, and the behavior the design
depends on. Skip APIs the codebase already uses the same way.

## Answers to open questions

- <Question from requirements.md>: <answer, citing C-ids>, or "deferred: <why>"

## Constraints

- <Performance, compatibility, licensing or platform limits that rule options in or out.>

## Citations

Every factual claim the design relies on gets an entry. Tier 3 sources are
pointers only (`role: pointer`). A claim you could not verify is
`status: unverified`, never a guess with a source attached.

```citations
- id: C1
  claim: <one sentence>
  source: <https URL or file:path>
  tier: 1
  quote: <exact text from the source, at least 20 characters>
  retrieved: <YYYY-MM-DD>
```
