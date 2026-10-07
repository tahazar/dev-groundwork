# Research: pr-map

- Requirements: `requirements.md` (approved 2026-10-07)
- Measurements: `spike/` holds the scripts and `spike/results.txt` their
  output, run against tahazar/ableton-workflow-helper at f099655.

## Summary for the design

| Job | Candidate | Evidence | Fits |
|---|---|---|---|
| Find constructs and map diff lines to them (boxes) | tree-sitter with the Python and TypeScript grammars | Parsed 128 TS and 50 Python files in under 0.3 s with no errors; a broken file still yields its other functions (C10, C10b, C11) | AC-1 to AC-3, AC-9, AC-19 |
| Resolve TypeScript references (solid arrows) | TypeScript LanguageService `findReferences` | Found exactly the 4 callers of `readClipIfPresent` in about 1 s (C13) | AC-4, AC-5, AC-7 |
| Resolve Python references (solid arrows) | jedi `Script.get_references` | Told the two `save_record` functions apart, including a call through a module alias (C16) | AC-4, AC-5, AC-7 |
| Name-only matches (dashed arrows) | tree-sitter tags-style queries | 26% of TS calls and 13% of Python calls match 2+ definitions by name, so names alone cannot draw solid arrows (C12) | AC-6 |
| Rejected: pyright for references | | Its command line reports diagnostics only (C18) | |

## Existing code to reuse

| What | Where | Use it for |
|---|---|---|
| Config and project root | `scripts/groundwork_config.py` (`load_config`, `project_root`, `walk_files`, `SKIP_DIRS`) | Finding the project and skipping `node_modules`, `dist`, `.venv` (C1) |
| Merge-base and diff against the base ref | `scripts/detect_workarounds.py` (`git`, `main`), `scripts/check_ac_coverage.py` (`approved_features_changed_since`) | The same base-ref handling; see duplicates below (C2) |
| Copying scripts into a project | `skills/setup/SKILL.md` section 3 | AC-22: the `cp` line lists each script by name, so the new script is added there (C3) |
| Workflow template | `templates/ci/groundwork.yml` | Same trigger (`pull_request`) and pinned checkout; needs `pull-requests: write` for the comment (C4) |
| Test harness | `tests/test_scripts.py` (`Repo`, `run_main`) | Temporary git repositories with a base branch, for fixture tests of AC-1 to AC-7 |

Duplicates the design should consolidate rather than copy a third time:

- "merge-base, then diff against the base" is written twice in Python
  (`detect_workarounds.py`, `check_ac_coverage.py`, one with the `git()`
  helper, one inline) and once in the workflow shell. A shared helper in
  `groundwork_config.py` would serve pr-map and both scripts.
- ableton-workflow-helper's `.github/workflows/groundwork.yml` has drifted
  from the template: it handles unusual file names with `git diff -z`,
  which the template lacks. Not pr-map's job, but setup copies the
  template, so it is worth a separate fix.

## External APIs and libraries

**tree-sitter (py-tree-sitter 0.26.0, grammars tree-sitter-python 0.25.0
and tree-sitter-typescript 0.23.2).** Installs from pre-built wheels with
no library dependencies (C5, C6). Queries return captures by name (C7).
Unrecognized text becomes an `ERROR` node and the rest of the tree is still
built (C8, C9), which the spike confirmed on a broken file (C11).
Tags queries follow a `@definition.*` / `@reference.*` naming convention
(C19). Etchpad's fork of tree-sitter-typescript extends `tags.scm` the same
way (C20).

Two caveats for the design:
- The TypeScript grammar's own `tags.scm` has no pattern for ordinary
  function or class declarations; those come from the JavaScript grammar's
  tags file, which the Python package does not load (C21). pr-map should
  ship its own query files, adapted from both (and from Etchpad's fork,
  MIT licensed).
- Tags capture names only. The docs describe no resolution step, and the
  only named application is "search-based code navigation" (C22).

**TypeScript LanguageService.** `findReferences(fileName, position)`
returns the referenced symbols with their reference entries (C13, C14).
The project's own TypeScript version should run it, so that references
match what its compiler sees.
- TypeScript 7 (npm `latest`, 7.0.2) is the native port and does not ship
  this JavaScript API under the same entry point (C15). pr-map must use a
  5.x or 6.x `typescript` package: the project's own when it is one of
  those, else a pinned one.

**jedi 0.20.0.** A static analysis library with `Script.get_references` and
`Script.goto` (C16, C17, C17b). It does not run the analysed code by default
(C23). Its docs warn that reference search can stop early when it gets too
complicated (C24): the design has to treat a short answer as possibly
incomplete, not as "no callers". MIT licensed (C25).

**Pyright** was considered because the project already uses it, but its
command line only reports diagnostics; references need its language
server (C18). Rejected for version 1.

## Addendum for the design: go to definition

Added 2026-10-07 during design, because the design asks "which definition
does this call point to?" at each call site, which research had not
measured.

- TypeScript's LanguageService declares `getDefinitionAtPosition` (C36).
  Inside one package it found the exact local function (C37).
- A call into another workspace package resolved to that package's built
  declaration file under `dist`, not its source (C38), and only works
  after a build. Pointing the compiler option `paths` (C39) at the
  package's source entry resolved the same call to the source definition,
  with no build (C40).
- jedi's `goto` follows imports when asked (C41) and resolved three calls
  named `save_record` to the two different functions they mean (C42).

## Answers to open questions

- Package line above the diagram: deferred to the owner after version 1, as
  the requirements say.
- Which Python constructs count: the Python grammar's tags query also tags
  module-level assignments as constants (C26c), besides functions and
  classes (C26, C26b). Version 1 maps functions,
  methods and classes, as AC-1 to AC-3 say; constants are deferred until
  a reviewer asks for them, because each module-level assignment would add
  a box with few arrows.
- GitHub's limits for AC-12 and AC-14:
  - Mermaid itself defaults to a 50,000-character diagram limit and a
    500-edge limit (C27, C28). GitHub documents Mermaid support but states
    no limit of its own (C29), so whether GitHub keeps these defaults is
    unverified. The design should split below both numbers.
  - A pull request comment's maximum length: unverified (C30). The design
    must detect a rejected comment and fall back to the job summary rather
    than rely on a number.
  - A job summary may hold 1 MiB per step, and a job shows at most 20 step
    summaries (C31, C32).
  - On pull requests from forks the token is read-only (C33), so AC-18's
    job-summary fallback is the normal path for forks, not an edge case.

## Constraints

- **Dependencies.** dev-groundwork's scripts use only the standard library
  today (C34). pr-map needs tree-sitter and jedi from PyPI and Node with
  `typescript` for TypeScript references. It should live apart from the
  stdlib-only checks (its own script and workflow job, with its own
  install step), so the existing checks keep running without installs.
- **Python version.** dev-groundwork targets Python 3.10 and later (C35);
  the spike ran on 3.13. The wheels' minimum Python version is checked in
  design.
- **Workflow permission.** Posting the comment needs write access to pull
  requests, which the existing template does not grant (C4).
- **Run time.** Parsing the whole repository took under 0.3 s; one
  `findReferences` call about 1 s with program setup; one jedi call under
  1 s (C10, C10b, C13, C16). A pull request with many changed functions makes
  many resolver calls, so the design should reuse one LanguageService and
  one jedi Project across calls.

## Citations

```citations
- id: C1
  claim: groundwork_config.py, the shared helper module, uses only the standard library so the scripts run without installs.
  source: file:scripts/groundwork_config.py
  tier: 1
  quote: Standard library only, so the scripts run in any project and in CI without installing anything.
- id: C2
  claim: detect_workarounds.py diffs against the merge base of the base ref.
  source: file:scripts/detect_workarounds.py
  tier: 1
  quote: base = git(root, "merge-base", args.base, "HEAD").strip()
- id: C3
  claim: The setup skill copies check scripts into the project with a cp line that names the scripts individually.
  source: file:skills/setup/SKILL.md
  tier: 1
  quote: cp ${CLAUDE_PLUGIN_ROOT}/scripts/groundwork_config.py ${CLAUDE_PLUGIN_ROOT}/scripts/check_citations.py
- id: C4
  claim: The workflow template runs on pull_request with read-only contents permission.
  source: file:templates/ci/groundwork.yml
  tier: 1
  quote: "pull_request: permissions: contents: read"
- id: C5
  claim: py-tree-sitter has no library dependencies and ships pre-compiled wheels.
  source: https://raw.githubusercontent.com/tree-sitter/py-tree-sitter/master/README.md
  tier: 1
  quote: The package has no library dependencies and provides pre-compiled wheels for all major platforms.
  retrieved: 2026-10-07
- id: C6
  claim: Grammar packages also ship pre-built wheels.
  source: https://raw.githubusercontent.com/tree-sitter/py-tree-sitter/master/README.md
  tier: 1
  quote: Tree-sitter language implementations also provide pre-compiled binary wheels.
  retrieved: 2026-10-07
- id: C7
  claim: py-tree-sitter's QueryCursor.captures() takes a tree's root node and returns the captures in it.
  source: https://raw.githubusercontent.com/tree-sitter/py-tree-sitter/master/README.md
  tier: 1
  quote: captures = query_cursor.captures(tree.root_node)
  retrieved: 2026-10-07
- id: C8
  claim: Text the parser does not recognize becomes an ERROR node in the tree.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter/master/docs/src/using-parsers/queries/1-syntax.md
  tier: 1
  quote: When the parser encounters text it does not recognize, it represents this node as `(ERROR)` in the syntax tree.
  retrieved: 2026-10-07
- id: C9
  claim: tree-sitter is designed to give useful results on code with syntax errors.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter/master/docs/src/index.md
  tier: 1
  quote: enough to provide useful results even in the presence of syntax errors
  retrieved: 2026-10-07
- id: C10
  claim: tree-sitter parsed the repository's 128 TypeScript files with no parse errors in 0.18 seconds.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "ts: files=128 definitions=723 call-refs=12810 files-with-parse-errors=0 seconds=0.18"
- id: C11
  claim: In a snippet containing a syntax error, the parser still found the functions ok and after.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "broken snippet: has_error True definitions found: ['ok', 'ok', 'after']"
- id: C12
  claim: In the TypeScript files, 26% of calls whose bare name matches a definition in the repository match two or more definitions.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: ".ts: calls whose name matches a repo definition=3916, of which match 2+ definitions=1016 (26%)"
- id: C13
  claim: The spike found 4 references to readClipIfPresent.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: references to readClipIfPresent=4
- id: C14
  claim: The LanguageService in TypeScript 5.9.3 declares findReferences.
  source: https://raw.githubusercontent.com/microsoft/TypeScript/v5.9.3/src/services/types.ts
  tier: 1
  quote: "findReferences(fileName: string, position: number): ReferencedSymbol[] | undefined;"
  retrieved: 2026-10-07
- id: C15
  claim: TypeScript 7 is the native port and does not expose the 5.x/6.x JavaScript API at the same entry point.
  status: unverified
- id: C16
  claim: jedi found 2 references to report.save_record, where a bare-name search of the repository finds 5 calls named save_record.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "awh_analysis/report.py:save_record: jedi references=2 bare-name calls in repo=5"
- id: C17
  claim: jedi is a static analysis tool for Python.
  source: https://raw.githubusercontent.com/davidhalter/jedi/master/README.rst
  tier: 1
  quote: Jedi is a static analysis tool for Python that is typically used in
  retrieved: 2026-10-07
- id: C18
  claim: Pyright's command line can output diagnostics in JSON.
  source: https://raw.githubusercontent.com/microsoft/pyright/main/docs/command-line.md
  tier: 1
  quote: option is specified on the command line, diagnostics are output in JSON format.
  retrieved: 2026-10-07
- id: C19
  claim: Tags queries name captures in a @role.kind format.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter/master/docs/src/4-code-navigation.md
  tier: 1
  quote: capture following the `@role.kind` capture name format, and another inner capture, always called `@name`, that pulls out
  retrieved: 2026-10-07
- id: C20
  claim: Etchpad's fork of tree-sitter-typescript tags function declarations as function definitions.
  source: https://raw.githubusercontent.com/etchpad/tree-sitter-typescript/development/queries/tags.scm
  tier: 1
  quote: "(function_declaration name: (identifier) @name) @definition.function"
  retrieved: 2026-10-07
- id: C21
  claim: tree-sitter-typescript's tree-sitter.json lists the JavaScript grammar's tags file among its tags queries.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter-typescript/master/tree-sitter.json
  tier: 1
  quote: '"queries/tags.scm", "node_modules/tree-sitter-javascript/queries/tags.scm"'
  retrieved: 2026-10-07
- id: C22
  claim: The tagging docs name search-based code navigation as the application.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter/master/docs/src/4-code-navigation.md
  tier: 1
  quote: A notable application of this is GitHub's support for [search-based code navigation]
  retrieved: 2026-10-07
- id: C23
  claim: jedi does not execute the analysed code by default.
  source: https://raw.githubusercontent.com/davidhalter/jedi/master/docs/docs/features.rst
  tier: 1
  quote: By default, no code is executed
  retrieved: 2026-10-07
- id: C24
  claim: jedi's reference search may stop early on complicated code.
  source: https://raw.githubusercontent.com/davidhalter/jedi/master/jedi/api/__init__.py
  tier: 1
  quote: quite hard to do for Jedi, if it is too complicated, Jedi will stop
  retrieved: 2026-10-07
- id: C25
  claim: jedi is MIT licensed.
  source: https://raw.githubusercontent.com/davidhalter/jedi/master/LICENSE.txt
  tier: 1
  quote: The MIT License (MIT)
  retrieved: 2026-10-07
- id: C26
  claim: The Python grammar's tags query tags function definitions.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter-python/master/queries/tags.scm
  tier: 1
  quote: "(function_definition name: (identifier) @name) @definition.function"
  retrieved: 2026-10-07
- id: C27
  claim: Mermaid's default maximum diagram text size is 50000 characters.
  source: https://raw.githubusercontent.com/mermaid-js/mermaid/develop/packages/mermaid/src/schemas/config.schema.yaml
  tier: 1
  quote: "The maximum allowed size of the users text diagram type: number default: 50000"
  retrieved: 2026-10-07
- id: C28
  claim: Mermaid's default maximum number of edges is 500.
  source: https://raw.githubusercontent.com/mermaid-js/mermaid/develop/packages/mermaid/src/schemas/config.schema.yaml
  tier: 1
  quote: "Defines the maximum number of edges that can be drawn in a graph. type: integer default: 500"
  retrieved: 2026-10-07
- id: C29
  claim: GitHub renders Mermaid from fenced code blocks.
  source: https://raw.githubusercontent.com/github/docs/main/content/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams.md
  tier: 1
  quote: To create a Mermaid diagram, add Mermaid syntax inside a fenced code block with the `mermaid` language identifier.
  retrieved: 2026-10-07
- id: C30
  claim: A pull request comment body has a documented maximum length.
  status: unverified
- id: C31
  claim: Each step's job summary is limited to 1 MiB.
  source: https://raw.githubusercontent.com/github/docs/main/content/actions/reference/workflows-and-actions/workflow-commands.md
  tier: 1
  quote: Job summaries are isolated between steps and each step is restricted to a maximum size of 1MiB.
  retrieved: 2026-10-07
- id: C32
  claim: A job displays at most 20 step summaries.
  source: https://raw.githubusercontent.com/github/docs/main/content/actions/reference/workflows-and-actions/workflow-commands.md
  tier: 1
  quote: A maximum of 20 job summaries from steps are displayed per job.
  retrieved: 2026-10-07
- id: C33
  claim: The GITHUB_TOKEN is read-only on pull requests from forks.
  source: https://raw.githubusercontent.com/github/docs/main/data/reusables/developer-site/pull_request_forked_repos_link.md
  tier: 1
  quote: The `GITHUB_TOKEN` has read-only permissions in pull requests from forked repositories.
  retrieved: 2026-10-07
- id: C34
  claim: dev-groundwork's scripts use only the standard library.
  source: file:README.md
  tier: 1
  quote: They use only the standard library.
- id: C35
  claim: dev-groundwork requires Python 3.10 or later.
  source: file:pyproject.toml
  tier: 1
  quote: requires-python = ">=3.10"
- id: C10b
  claim: tree-sitter parsed the repository's 50 Python files with no parse errors in 0.07 seconds.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "py: files=50 definitions=494 call-refs=4191 files-with-parse-errors=0 seconds=0.07"
- id: C17b
  claim: jedi's API includes Script.get_references.
  source: https://raw.githubusercontent.com/davidhalter/jedi/master/README.rst
  tier: 1
  quote: "- ``jedi.Script.get_references``"
  retrieved: 2026-10-07
- id: C26b
  claim: The Python grammar's tags query tags class definitions.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter-python/master/queries/tags.scm
  tier: 1
  quote: "name: (identifier) @name) @definition.class"
  retrieved: 2026-10-07
- id: C26c
  claim: The Python grammar's tags query tags module-level assignments as constants.
  source: https://raw.githubusercontent.com/tree-sitter/tree-sitter-python/master/queries/tags.scm
  tier: 1
  quote: "(module (expression_statement (assignment left: (identifier) @name) @definition.constant))"
  retrieved: 2026-10-07
- id: C36
  claim: TypeScript 5.9.3's LanguageService declares getDefinitionAtPosition(fileName, position).
  source: https://raw.githubusercontent.com/microsoft/TypeScript/v5.9.3/src/services/types.ts
  tier: 1
  quote: "getDefinitionAtPosition(fileName: string, position: number): readonly DefinitionInfo[] | undefined;"
  retrieved: 2026-10-07
- id: C37
  claim: getDefinitionAtPosition resolved a call to readClipIfPresent to its local definition at line 2278.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "packages/cli/src/index.ts:2278 local function readClipIfPresent"
- id: C38
  claim: Without a paths override, a CLI call to parseNotation resolved to core's built declaration file.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "packages/cli/node_modules/@awh/core/dist/notation/barbeat.d.ts:39 function parseNotation"
- id: C39
  claim: TypeScript 5.9.3's compiler options include paths.
  source: https://raw.githubusercontent.com/microsoft/TypeScript/v5.9.3/src/compiler/types.ts
  tier: 1
  quote: "paths?: MapLike<string[]>;"
  retrieved: 2026-10-07
- id: C40
  claim: With paths pointing @awh/core at core's source entry, the same call resolved to the source definition.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "packages/core/src/notation/barbeat.ts:98 function parseNotation"
- id: C41
  claim: jedi's goto can follow imports.
  source: https://raw.githubusercontent.com/davidhalter/jedi/master/jedi/api/__init__.py
  tier: 1
  quote: ":param follow_imports: The method will follow imports."
  retrieved: 2026-10-07
- id: C42
  claim: jedi's goto resolved the call at line 589 named save_record to drumstats.py rather than report.py.
  source: file:docs/specs/pr-map/spike/results.txt
  tier: 1
  quote: "save_record at awh_analysis/__main__.py:589 -> ['awh_analysis/drumstats.py:372']"
```
