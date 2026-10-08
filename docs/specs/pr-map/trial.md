# Trial: pr-map in ableton-workflow-helper

- Task: 11 in `tasks.md`.
- Date: 2026-10-08.
- Pull request: tahazar/ableton-workflow-helper#33, "ci: Trial pr-map
  (do not merge)", a draft. Only the owner merges or closes it.
- pr-map version: `scripts/pr_map/` and `templates/ci/pr-map.yml` at
  5fc7fd1 (main after #20).
- Result: **AC-22 stays deferred.** The workflow runs, posts one comment
  and edits it in place, and every arrow on the trial's own code change
  is right. But the trial found arrows that break AC-7 and one crash that
  breaks AC-20; see "What blocks AC-22".

## What the trial did

The trial pull request has three commits:

1. `ci: Add the pr-map trial workflow`.
   - `scripts/pr_map` was copied into `.groundwork/bin/pr_map/`, using
     the file list of `skills/setup/SKILL.md` step 3, without
     `node_modules`.
   - `templates/ci/pr-map.yml` was copied unchanged into
     `.github/workflows/pr-map.yml`.
   - `.groundwork/bin/groundwork_config.py` was updated to the same
     commit, because `pr_map.py` imports `merge_base` and `diff_against`
     from it and awh's copy predated task 1 (finding 5).
   - No tooling change was needed. awh's oxlint and oxfmt cover
     `packages/` and `scripts/`, ruff and pyright cover `analysis/`, and
     its pnpm workspace covers `packages/*`, so none of them reach
     `.groundwork/`. actionlint 1.7.12, the awh CI pin, passes the
     workflow.
2. `fix: Keep accented letters when slugifying names`. This is a real bug
   fix with tests that failed first.
   - `slugify` in `packages/core/src/library/entry.ts` dropped non-ASCII
     letters, so "Café Bass" became `caf-bass`.
   - A new `asciiSlug` decomposes the text first. `slugify` and the CLI's
     `slugifySectionName` (`packages/cli/src/endless/plan.ts`) both call
     it.
   - The expected map is 1 added box, 2 changed boxes, and callers from
     the CLI package into core through the workspace `paths` mapping.
3. `test: Cover the numbered fallback for a section name with no
   letters`. This is a test-only push, to see the comment edited rather
   than posted again (AC-16).

The comment was checked against the code in three ways:
- by reading it;
- by a script that opens every arrow's call site;
- by running `git grep` for each changed function.

The local run used the same pinned packages, on Python 3.13 with awh's
`node_modules` installed. Its JSON was compared with the comment's text
list.

## Checks and evidence

| Check | Criteria | Result | Evidence |
|---|---|---|---|
| The pr-map check is green and stayed green | AC-21 | pass | Run 37804710241 on 969b511 and run 37805190627 on 3db93dd: both `success`. |
| awh's other checks | | pass | Lint, Node, Python and Groundwork were all green on both 969b511 and 3db93dd. Nothing failed because of the copied files. |
| One comment, by `github-actions[bot]`, with the marker | AC-15 | pass | Comment 6063816388, created 15:56:01. |
| A new push edits it in place | AC-16 | pass | After the push of 3db93dd, the same comment id had `updated_at` 16:00:01. The PR still has one comment, and GitHub sent `issue_comment.edited`, not `created`. |
| The header names the base and head | AC-17 | pass | "Computed from `691e759` (base) to `969b511` (head)", then "… to `3db93dd` (head)". Both are the PR's base and head short SHAs. |
| A box for every changed, added and removed construct, with status and `path:line` | AC-1, AC-2, AC-3, AC-8 | pass | `asciiSlug` added at `entry.ts:42`, `slugify` changed at `entry.ts:51`, `slugifySectionName` changed at `plan.ts:62`, `merge_base` and `diff_against` added. The 150 other added boxes are the copied pr-map code (finding 4). The line numbers match the head commit. No construct was removed. |
| Every arrow is a real reference | AC-7 | **fail** | All 513 arrows sit on an identifier with the target's name, inside the source box's file. But 36 of the 49 possible arrows join a TypeScript site to a Python definition or the reverse (finding 1), and a Python annotation draws a possible arrow to a constructor (finding 3). |
| Exact arrows resolve to the right target | AC-5 | pass | Sampled exact arrows whose target name has several boxes all point at the right definition. Every arrow on the trial's code change was checked by hand (next row). |
| No missing callers | AC-4, AC-11 | pass | `git grep -w` finds 17 calls of `slugify`: 10 in `buildProgram` (`cli/src/index.ts`), 1 in `layerFileName` (`cli/src/layers.ts`) and 6 in `core/test/library.test.ts`. Each is an exact arrow. The two callers of `asciiSlug` (`slugify`, and `slugifySectionName` across packages) and the one caller of `slugifySectionName` (`sectionsFromReference`) are exact arrows too. |
| Possible arrows say why | AC-6 | partial | Each has a reason. 43 sites that jedi does resolve came out as "unresolved" (finding 2), and one reason is misleading (finding 6). |
| The diagram renders | AC-12 | pass, but unreadable | One diagram: 19,011 characters, 180 boxes, 343 edges, under both budgets. mermaid-cli 11.4.2 renders it without errors, as a 6,806 × 12,894 px canvas. At GitHub's comment width the labels are too small to read; that comes from finding 4. Whether github.com draws it was not checked from this session. |
| The text list is complete | AC-13 | pass | 513 rows, one per arrow, matching the JSON. Unresolved calls (67), "refers to" sites and library calls per file are listed. |
| The job summary and the `pr-map` artifact exist | AC-14 | partial | The artifact exists: id 11562381075, 37,126 bytes, holding `pr-map.md` and `pr-map.json`, according to the API and the upload step's log. The job summary could not be read from this session: the run page answered 403 through the session's proxy, and the check-run API does not return step summaries. Not checked; the owner can open the run page. |
| The comment fits | AC-14 | not exercised | GitHub accepted a 171,125-character comment, so the 422 shrinking path did not run. |
| Warnings in the log | | none | Neither run logged a warning: no TypeScript fallback and no resolver failure. |

### Timings

| Run | Head | Job | Install steps | Mapping step |
|---|---|---|---|---|
| 37804710241 | 969b511 | 35 s | 3 s (pip 2 s, npm 1 s) | 23 s |
| 37805190627 | 3db93dd | 54 s | 6 s | 36 s |
| Local, 4 threads | 969b511 | | | 24 s |

Most of the mapping time goes to the 150 copied pr-map constructs and
their roughly 2,300 resolver queries. A pull request that changes only
awh's own code should be much faster.

## What the trial found

### 1. Name matches cross languages, giving possible arrows that break AC-7

Step 5 of the design matches every identifier in the repository whose
text equals a box's match key, whatever the file's language. When the
resolver cannot answer, step 6 turns that into a possible arrow. So a
TypeScript property points at a Python function, and the reverse. Such a
reference cannot exist.

- `packages/core/src/bridge/paths.ts:60`, `segments.push({ kind, index }
  as PathSegment)`, draws a possible arrow to
  `.groundwork/bin/pr_map/resolve.py::index`.
- `.groundwork/bin/pr_map/resolve.py:497`, `parent = name.parent()`,
  draws a possible arrow to
  `packages/extension/types/ableton-sdk-shim.d.ts::DataModelObject.parent`.
- `packages/core/test/bass.test.ts:253`, `Number(meta.root)`, draws a
  possible arrow to `.groundwork/bin/pr_map/render.py::_groups.root`.
- In CI only, `packages/core/src/bridge/server.ts:121`,
  `server.close(...)`, draws possible arrows to `resolve.py::TypeScript.close`
  and `resolve.py::Resolver.close`.

The scale:
- Locally, 26 of 39 possible arrows are cross-language.
- In CI, 36 of 49 are. The 10 extra ones appear because the runner has
  no awh `node_modules`, so `.close()` and `.split()` on Node values are
  no longer recognised as library calls. The map therefore depends on
  whether the project's dependencies are installed.

The same leak fills the unresolved-call list. The Python `c.status` at
`pr_map.py:146` lists 8 TypeScript `status` members as options.

The fixture repositories in `tests_pr_map/` never have the same name in
both languages, so the tests could not catch this.

### 2. Reusing one jedi `Script` per file loses answers

`Resolver._script` caches one `jedi.Script` per file, and every
`definition_at` and `references` call on that file reuses it. After some
earlier queries on the same `Script`, `goto` returns nothing for sites
that it resolves when asked first:

- `resolve.py:225:23`, `raise self._fail(...)` inside `TypeScript._start`,
  is a possible arrow with reason "unresolved". The identical call at
  `resolve.py:186:23` inside `TypeScript.ask` is exact.
- A fresh `Resolver` asked only `definition_at(".../resolve.py", 225, 23)`
  answers `TypeScript._fail` at line 260.
- 17 earlier `goto` calls on the same `Script` are enough to lose the
  answer, all in `TypeScript.ask` and `TypeScript.close`: lines
  192:26, 193:74, 210:36, 219:23, 208:25, 210:30, 211:30, 211:35,
  213:30, 214:30, 216:19, 216:24, 217:37, 217:58, 217:80, 224:20 and
  224:27. Raising jedi's `total_function_execution_limit` does not
  help.
- Replaying the run's 2,267 `definition_at` queries on `resolve.py`:
  - with one shared `Script`, 2,143 are answered in 3.7 s;
  - with a fresh `Script` per query, 2,186 are answered in 13.0 s.
  - 43 sites are answered only with a fresh `Script`, and none only
    with the shared one.

Each lost answer becomes a possible arrow, or a silent omission, for a
reference jedi can in fact resolve. That goes against AC-5, and the
callee rule then guesses its target by name.

### 3. A type annotation becomes a possible call of a constructor

At `.groundwork/bin/pr_map/github.py:167`, `def find_comment(api: Client,
...)` draws possible arrows to both `Client` and `Client.__init__`.

- jedi's `goto` returns nothing on the annotation; `infer` returns the
  class.
- The name match uses the class name as `__init__`'s match key. With an
  empty answer, the verdict falls to the "Nothing" row, so a non-call
  site becomes a possible constructor call.
- The design says an annotation counts as the class, and only a real
  call counts as the constructor (design step 6, "A class with its
  constructor").

### 4. The map includes pr-map's own copy

The trial's own diff adds `.groundwork/bin/`, so the map has:
- 150 added boxes for the copied pr-map code;
- the 2 new `groundwork_config.py` helpers;
- 3 boxes for the code the reviewer cares about.

The diagram is 180 boxes on a 6,806 × 12,894 px canvas, and the change
under review is lost in it. This will happen on the pull request that
`/dev-groundwork:setup` produces (AC-22), and on every later pull request
that refreshes the copied scripts. `.groundwork/` holds tooling copied
from dev-groundwork, not project code.

### 5. An older `groundwork_config.py` crashes pr-map with no comment

`pr_map.py` imports `groundwork_config` at module level, outside the
guarded imports that #20 added, and uses `merge_base` and `diff_against`
from task 1. With awh's previous `groundwork_config.py`, the run stops at
import:

```
ImportError: cannot import name 'diff_against' from 'groundwork_config'
```

That happens before `main`, so with `--post` no comment is posted. The
workflow step is `continue-on-error`, so the check is green and nobody is
told. That breaks AC-20.

Who it affects:
- A project set up before task 1 that copies only `pr_map/`, as task 11
  was worded, hits this.
- `/dev-groundwork:setup` copies `groundwork_config.py` in the same
  step, so a fresh setup does not. Re-running only part of the copy
  would.

### 6. A possible arrow says "unresolved import" when the import resolved

At `analysis/awh_analysis/__main__.py:130`, `result["deltas"].items()`
draws a possible arrow to `Candidates.items` with reason "unresolved
import".

- `result` comes from `ab.ab_compare(...)`, and `ab` is a repository
  module that jedi resolves.
- What is unknown is the type of the returned value, not the import.
- The arrow itself is the expected "could not rule out" case; only the
  reason is wrong.

### Observations, not bugs

- The possible arrows that remain after finding 1 are mostly
  `.split()`, `.items()` and similar on values jedi cannot type, pointing
  at the copied pr-map's own `split` and `items`. That is the design's
  rule for an unresolved callee with one same-named box. On an ordinary
  awh pull request there would be far fewer.
- Each run rebuilds the map in 23 to 36 s for this pull request, well
  inside a review's patience. The install steps took 3 to 6 s.

## What blocks AC-22

AC-22 stays `(deferred)` in `requirements.md` until these are fixed and
a second trial passes:

- Finding 1 (AC-7): cross-language possible arrows.
- Finding 3 (AC-7): a possible constructor arrow from an annotation.
- Finding 5 (AC-20): the unguarded `groundwork_config` import.
- Finding 4 is what the setup pull request itself would show. The owner
  should decide whether `.groundwork/` is skipped before setup starts
  adding the map.

Findings 2 and 6 make the map less useful, but they do not draw an
arrow without a reference. They should be fixed, but they do not block
on their own.

## Proposed follow-up tasks

Each starts with a failing test built from its example above. No
pr-map code was changed in the trial.

- **11a. Match names within one language.**
  - A name match is a candidate only when the site's file and the box's
    file are the same language (`.ts`/`.tsx`, or `.py`).
  - The unresolved-call options are filtered the same way.
  - Failing example: a fixture with a TypeScript `{ index }` shorthand
    and a Python `def index()`. Today it draws a possible arrow between
    them.
- **11b. Ask jedi with a fresh `Script` per query, or per box, and
  measure.**
  - Failing example: `resolve.py` at 5fc7fd1. After the 17 queries
    listed in finding 2, `definition_at` at 225:23 answers nothing; it
    should answer `TypeScript._fail`.
  - Weigh the 3.5 × time on that file against the lost answers. One
    `Script` per box may keep most of the speed.
- **11c. Constructor candidates only at calls.**
  - A name-match candidate for a constructor box (`__init__`, `__new__`,
    `constructor`), matched by its class's name, counts only when the
    site is the function of a call (or a `new`).
  - When `goto` answers nothing for a name in an annotation, try `infer`
    before calling the site unresolved.
  - Failing example: `def f(api: Client)` beside `class Client` with an
    `__init__`. Today it draws possible arrows to `Client.__init__` and
    `Client`.
- **11d. Skip `.groundwork/` when mapping.** This needs an owner decision
  (finding 4).
  - Add it to pr-map's skip list, so copied Groundwork tooling never
    appears on a project's map.
  - Failing example: the trial pull request, whose map has 152 boxes
    from `.groundwork/bin/`.
- **11e. Guard the `groundwork_config` import like the package imports.**
  - An `ImportError` there should become a `MapError` that names the
    missing helper and says to re-run setup's copy step.
  - Failing example: run `pr_map.py --post` beside a `groundwork_config.py`
    without `diff_against`. Today it exits at import with no comment;
    it should post "pr-map could not build the map: ..." and exit 0.
- **11f. Name the right reason when an import resolves.** Use
  "unresolved" when the leftmost name's import is a repository module
  jedi resolves.
  - Failing example: `x = repo_module.make(); x.items()`. Today the
    reason is "unresolved import"; it should be "unresolved".
- **11g. Second trial.**
  - After 11a, 11c, 11e, and 11d if the owner wants it, repeat this
    trial on a fresh awh pull request.
  - Lift AC-22's `(deferred)` only when every check above passes.
