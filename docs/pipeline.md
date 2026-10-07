# The development pipeline

A feature moves through six stages. Each stage has one output and one gate.
Work does not start on a stage until the gate before it passes.

| Stage | Skill | Output | Gate |
|---|---|---|---|
| 1. Requirements | `/dev-groundwork:requirements` | `requirements.md` | You approve the acceptance criteria |
| 2. Research | `/dev-groundwork:research` | `research.md` | `check_citations.py` passes; every open question is answered or deferred |
| 3. Design | `/dev-groundwork:design` | `design.md`, `tasks.md` | `design-reviewer` finds nothing blocking; you approve |
| 4. Tests | `/dev-groundwork:acceptance-tests` | Failing tests, one or more per criterion | `check_ac_coverage.py` passes; you review the tests |
| 5. Implement | `/dev-groundwork:implement` | Code, one task per session | Hooks: project checks before each commit, test files locked |
| 6. Review | `/dev-groundwork:review` | Findings | `code-reviewer` finds nothing blocking; `detect_workarounds.py` and CI pass |

Spec files live in `<specDir>/<feature>/` (default `docs/specs/<feature>/`).

## When to skip stages

If you can describe the diff in one sentence, skip stages 1 to 3 and write
the test first (`/dev-groundwork:test-first`). This is the threshold
Anthropic's Claude Code guide uses for skipping a plan [1]. A bug fix
starts with `/dev-groundwork:debug`, which finds the root cause before any
code changes, and continues test-first with a test that reproduces the
bug. Both prove the test fails without the change: a test never seen
failing may not test the change at all. The two skills adapt the
systematic-debugging, test-driven-development and
verification-before-completion skills from Superpowers [8].

## Why each stage exists

**Requirements are acceptance criteria, not prose.** Each criterion is one
EARS sentence ("When <trigger>, the system shall <response>") with an ID,
`AC-1`, `AC-2`, and so on [2]. One criterion becomes one or more tests, so
"done" has a mechanical meaning. The agent interviews you first, because
the hard parts of a feature are the ones you have not thought of yet [1].

**Research comes before design.** Two things go wrong when an agent designs
from memory: it rebuilds something the codebase already has, and it calls
APIs that do not exist or behave differently than it assumes. Amazon's
CloudAPIBench study measured the second: GPT-4o made valid calls to
rarely used cloud APIs 38.58% of the time, and 47.94% with documentation
retrieved. Retrieving documentation for every call hurt common APIs, so
look up what is unfamiliar or version-sensitive, not everything [3].

**Design means at least two designs.** Your first idea for a module is
unlikely to be the best one; compare alternatives before choosing [4].
For LLMs the effect is measured: PlanSearch found that models repeat
near-identical wrong attempts, and that searching over different
natural-language plans raised Claude 3.5 Sonnet's LiveCodeBench pass@200
from 60.6% to 77.0%. The gain tracked how different the ideas were [5].
Alternatives must differ in structure, not in naming.

**Designs are checked against written rules.** GitHub's Spec Kit gates
every plan on project articles, among them test-first (Article III), a
simplicity limit (Article VII) and "Use framework features directly rather
than wrapping them" (Article VIII) [6]. The project rules template in
`templates/project-rules.md` plays the same role here.

**Tests come before code, and someone other than the implementer grades
them.** Tests written after the code tend to check what the code does
instead of what was asked. Tests the implementer writes and then grades
itself against can share its mistakes. The tests are reviewed by you,
traced to criteria by a script, and locked while implementation runs.

**Hooks, not instructions, for rules that must always hold.** Instructions
in CLAUDE.md are advisory; hooks run every time [1]. The project's checks
and the test lock are hooks.

**Check at the commit, not on every edit.** Code is often half-finished in
the middle of a change: an import before its use, a rename before its
callers. Linting every intermediate state pushes the agent to fix or
silence warnings that would have resolved on their own. The checks run
when Claude commits instead, and a failure blocks the commit. With small,
frequent commits that is still often, and a failure caught there costs a
local run instead of a red CI cycle. CI runs the same checks on every push
and stays the source of truth.

**Review happens in a fresh context.** A reviewer that did not write the
code is not anchored on the author's reasoning [1]. A reviewer asked to find
gaps will report some even in sound work, so it reports only findings that
affect correctness or the stated criteria [1].

## Reward hacking

Every check the agent can see is a target it can satisfy without doing the
work. Anthropic defines reward hacking as hard-coding answers or
special-casing the visible examples, and detects it in its own models with
held-out tests and classifiers [7]. The pipeline applies the same idea:

- **Check substance, not format.** "Has a citation" is gameable; "the
  quoted text appears at the cited URL, on a domain of the claimed tier" is
  not (`check_citations.py`). Whether the quote supports the claim is
  judged by a separate `citation-verifier` that sees only the claim and the
  quote.
- **Separate writing from grading.** Criteria and tests are approved by
  you before implementation; the implementer cannot edit tests while
  they are locked.
- **Use checks the implementer cannot see or predict.** Keep some
  acceptance tests out of the implementer's reach, and prefer
  property-based tests with generated inputs, so hard-coding the visible
  cases fails.
- **Detect the usual workarounds mechanically.** `detect_workarounds.py`
  flags added skips, lint and type suppressions, coverage exclusions and
  edits to coverage thresholds in the diff.
- **Measure whether tests catch bugs.** Coverage shows lines ran. Mutation
  testing, where the project supports it, shows whether a test fails when
  the code is wrong.
- **Make "unverified" a valid answer.** If gaps are punished, the agent
  fills them with invented sources. A claim marked unverified is fine; a
  claim with a fake source is a blocking finding.

## Source tiers

Not all sources are equal. A design decision needs a Tier 1 source, or a
Tier 2 source with the gap stated. Tier 3 sources can point to a Tier 1
source but cannot support a decision on their own.

| Tier | Examples |
|---|---|
| 1 | Official documentation pinned to a version; standards and RFCs; the library's source code; a paper read in full; the project's own code and measurements |
| 2 | Engineering blogs from the vendor or maintainers; preprints; conference talks by the authors |
| 3 | Aggregators, mirrors, SEO pages, skill directories, Medium posts, AI-written summaries |

An example of why: a documentation mirror of Spec Kit labels its simplicity
gate "Article II"; Spec Kit's own `spec-driven.md` numbers it Article VII.

Each project lists its trusted domains per tier in `.groundwork/config.json`.
Domains not listed are Tier 3.

## Sources

Retrieved 2026-10-07 unless noted.

1. Anthropic, "Best practices for Claude Code."
   https://code.claude.com/docs/en/best-practices (Tier 1)
2. A. Mavin et al., "Easy Approach to Requirements Syntax (EARS)," 17th
   IEEE International Requirements Engineering Conference, 2009. (Tier 1,
   cited from the paper; not fetched)
3. "On Mitigating Code LLM Hallucinations with API
   Documentation," Amazon Science.
   https://cdn.amazon.science/8f/83/7407a5634a80a39e82b52ae935fe/on-mitigating-code-llm-hallucinations-with-api-documentation.pdf
   (Tier 1; figures taken from the abstract)
4. J. Ousterhout, *A Philosophy of Software Design*, chapter 11, "Design it
   Twice." (Tier 1, cited from the book; not fetched)
5. "Planning In Natural Language Improves LLM Search For
   Code Generation," ICLR 2025. https://iclr.cc/virtual/2025/poster/31034
   (Tier 1; figures taken from the abstract)
6. GitHub, Spec Kit, `spec-driven.md`.
   https://github.com/github/spec-kit/blob/main/spec-driven.md (Tier 1)
7. Anthropic, "System Card: Claude Opus 4 & Claude Sonnet 4," May 2025.
   https://www.anthropic.com/claude-4-system-card (Tier 1)
8. J. Vincent, Superpowers v6.4.2, `skills/systematic-debugging`,
   `skills/test-driven-development` and
   `skills/verification-before-completion`, MIT license.
   https://github.com/obra/superpowers (Tier 1 for what the skills say;
   adapted, not copied)
