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
- [ ] 7. Graph assembly: candidates from both sources, verdicts, callers of
  removed boxes, overrides and implementations, unresolved calls, JSON
  output. (AC-3, AC-4, AC-6, AC-7, AC-11)
- [ ] 8. `render.py`: Mermaid diagrams, splitting under the budgets, the
  text list, header and notes. (AC-8, AC-10 to AC-13, AC-17, AC-19)
- [ ] 9. `github.py` and the entry point: comment upsert by marker and
  author, the 403 and fork path, the 422 shrinking sequence, job summary,
  top-level failure handling, exit codes. Tested against a local HTTP
  server. (AC-14, AC-16, AC-18, AC-20, AC-21)
- [ ] 10. `templates/ci/pr-map.yml` with the concurrency group, pinned
  actions (look up the upload-artifact pin from its release tag) and
  install steps that record failures instead of failing. actionlint
  clean. (AC-15, AC-21)
- [ ] 11. Trial in ableton-workflow-helper: copy `scripts/pr_map/` and the
  workflow by hand, open a small pull request, and check the comment
  against the code. Record what the trial found. (AC-22 stays deferred
  until this passes)
- [ ] 12. Documentation: README rows for the new check and its install
  needs, and a line in `docs/pipeline.md`.
