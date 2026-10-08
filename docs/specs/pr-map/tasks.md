# Tasks: pr-map

One task per session. Each task is small enough to review in one sitting
and names the criteria it moves toward passing. The acceptance tests
(stage 4) are written and approved before task 2 starts; tasks 2 to 9
make them pass.

- [x] 1. Move the merge-base diff into `groundwork_config.py`
  (`merge_base`, `diff_against`), and switch `detect_workarounds.py` and
  `check_ac_coverage.py` to it. A refactor with no behaviour change: the
  existing tests pass unchanged. (prerequisite; research's duplicate)
- [x] 2. `scripts/pr_map/` skeleton: pinned `requirements.txt`,
  `package.json` and `package-lock.json`, the `tests_pr_map/` directory
  with the fixture builders, and a CI job in this repository that installs
  them and runs the tests. (AC-9, groundwork for the rest)
- [x] 3. `constructs.py` and the two query files: constructs with
  qualified names and innermost nesting, identifier sites, byte-to-character
  columns, syntax-error lines. (AC-1 to AC-3 groundwork, AC-8, AC-9, AC-19)
- [x] 4. Classification against the diff: changed, added, removed, with
  innermost attribution of changed lines. (AC-1, AC-2, AC-3, AC-10)
- [x] 5. Python resolver: `definition_at` and reference search with jedi,
  and the verdict rules. (AC-4 to AC-7 for Python)
- [x] 6. TypeScript resolver: `resolve_ts.cjs`, the `paths` mapping for
  workspace packages, and the Python side of the protocol, including the
  fallback when Node or the helper is unavailable. (AC-4 to AC-7 for
  TypeScript)
- [x] 7. Graph assembly: candidates from both sources, verdicts, callers of
  removed boxes, overrides and implementations, unresolved calls, JSON
  output. (AC-3, AC-4, AC-6, AC-7, AC-11)
- [x] 8. `render.py`: Mermaid diagrams, splitting under the budgets, the
  text list, header and notes. (AC-8, AC-10 to AC-13, AC-17, AC-19)
- [x] 9. `github.py` and the entry point: comment upsert by marker and
  author, the 403 and fork path, the 422 shrinking sequence, job summary,
  top-level failure handling, exit codes. Tested against a local HTTP
  server. (AC-14, AC-16, AC-18, AC-20, AC-21)
- [x] 10. `templates/ci/pr-map.yml` with the concurrency group, pinned
  actions (look up the upload-artifact pin from its release tag) and
  install steps that record failures instead of failing. actionlint
  clean. (AC-15, AC-21)
- [x] 11. Trial in ableton-workflow-helper: copy `scripts/pr_map/` and the
  workflow by hand, open a small pull request, and check the comment
  against the code. Record what the trial found. (AC-22 stays deferred
  until this passes) Recorded in `trial.md`: it did not pass, and AC-22
  stays deferred until the follow-up tasks listed there (11a to 11g) are
  done.
Follow-ups from the trial (`trial.md`, "Proposed follow-ups"), and
revision 2 (design, "Revision 2"). The owner approved 11a to 11f and
skipping `.groundwork/` on 2026-10-08.

- [ ] R0. Step 0: the owner checks the test comment on
  ableton-workflow-helper #33 (collapsed sections, mermaid version). The
  build waits for the answer.
- [ ] R1. Acceptance tests for revision 2 (stage 4): the new criteria, and
  each changed assertion in `test_render.py` with its reason. Approved
  before R2. (AC-11, AC-12, AC-23 to AC-30)
- [ ] 11a. Match names within one language. (AC-7)
- [ ] 11b. A fresh jedi `Script` per query or per box. (AC-5)
- [ ] 11c. Constructor candidates only at calls and `new`. (AC-7)
- [ ] 11e. Guard the `groundwork_config` import like the package imports.
  (AC-20)
- [ ] 11f. Name the right reason when an import resolves. (AC-6)
- [ ] R2. Skip `.groundwork/` and count it in the notes (11d); add
  `files` to the map. (AC-23 data, AC-30)
- [ ] R3. Labels and outlines: the three-character escape, no fills, the
  outline classes. (AC-28, AC-29)
- [ ] R4. The file map. (AC-23, AC-24)
- [ ] R5. File sections, the collapse, splitting per diagram, and the 422
  shrinking order. (AC-11, AC-12, AC-14, AC-25 to AC-27)
- [ ] 11g. Second trial in ableton-workflow-helper, viewed on a phone and
  in dark mode.
- [ ] 12. Documentation: README rows for the new check and its install
  needs, and a line in `docs/pipeline.md`.
