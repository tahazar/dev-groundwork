---
name: research
description: Stage 2 of the development pipeline. Find existing code to reuse and authoritative documentation for the APIs a feature depends on, and record each claim as a checkable citation in research.md. Use after requirements are approved and before design.
argument-hint: <feature-name>
arguments: [feature]
---

# Stage 2: research for `$feature`

Input: approved `<specDir>/$feature/requirements.md`.
Output: `<specDir>/$feature/research.md`, from
`${CLAUDE_PLUGIN_ROOT}/templates/spec/research.md`.

## 1. Existing code (subagent)

Use a subagent so the search does not fill this context:

> Search this repository for code that `$feature` should reuse or extend:
> helpers, parsers, validation, data models, patterns that existing
> features of the same kind follow. For each, give the file path, the
> symbol, and one line on what it does. Report duplicates you notice: the
> same logic implemented more than once.

Record each item with a `file:` citation. If the codebase already has two
or more implementations of something the feature needs, say so: the design
should consolidate rather than add a third.

## 2. External documentation

For each API or library the feature uses that is unfamiliar, rarely used,
or version-sensitive:

- Find the official documentation for the version the project uses (check
  the lockfile). Prefer the vendor's docs, the library's source or its
  repository over any other page.
- Use a documentation tool when one is connected (for example a vendor's
  MCP documentation server); otherwise fetch the page.
- Record the behavior the design depends on, quoting the source exactly.

Skip APIs the codebase already uses in the same way; the existing code is
the better reference.

## 3. Source rules

Tiers are defined in the plugin's `docs/pipeline.md` and the project's
`.groundwork/config.json`.

- A Tier 3 page (aggregator, mirror, blog repost, AI summary) is only a
  pointer. Follow it to the Tier 1 source and cite that instead.
- Quote exactly. The check script fetches each URL and fails a quote it
  cannot find.
- If you cannot confirm something, write `status: unverified`. An honest
  gap is fine; a citation that does not support its claim is a blocking
  problem.
- When two Tier 1 sources disagree, record both and say which the design
  should follow.

## 4. Check

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_citations.py --require <specDir>/$feature/research.md
```

Fix every failure. Then run the `citation-verifier` agent on the entries
that the design will depend on, giving it only each entry's claim and
quote. Fix or downgrade any entry it says the quote does not support.

## 5. Gate

Every open question from requirements.md is answered (with citations) or
marked deferred with a reason. Report the check output and any unverified
claims to the user, then move to design.
