# Design: pr-map

- Status: draft
- Requirements: `requirements.md`; research: `research.md`

## Context

Nothing in dev-groundwork reads code structure today. Its scripts read
diffs and text, and use only the standard library (C34). pr-map has to do
three things:

1. find the functions, methods and classes a pull request changed, added
   or removed;
2. find what calls them and what they call, drawing an arrow solid only
   when the language's own tooling confirms it;
3. post the result on the pull request.

Research found two jobs with different tools. tree-sitter finds constructs
quickly and survives broken code (C10, C10b, C11). Names alone are
ambiguous for about a quarter of TypeScript calls (C12), so arrows need a
resolver: the TypeScript LanguageService (C13, C36, C37) and jedi (C16,
C41, C42).

## Options

### Option A: candidates from tree-sitter, verdicts from each language's resolver

One Python program owns the whole pipeline: diff, constructs, graph,
rendering, posting.

- **Boxes.** tree-sitter parses each changed file at the base and head
  commits. Tags-style queries find definitions and call sites (C19, C26,
  C26b), adapted from the grammars' own tags files and Etchpad's fork
  (C20, C21).
- **Arrows, in two steps.** Every arrow starts as a candidate: a call site
  whose name matches a box. The language's resolver then gives a verdict
  by answering one question at that call site: "where is this defined?"
  - Python: jedi `goto` with `follow_imports` (C41), in the same process.
  - TypeScript: `getDefinitionAtPosition` (C36), in a small Node helper
    the Python program starts once and talks to over standard input and
    output. One LanguageService serves each tsconfig, and is reused across
    calls.
  - The verdict decides the arrow:
    - it lands on the box: a solid arrow;
    - it lands elsewhere: no arrow;
    - it lands nowhere or on several places: a dashed "possible" arrow.
- **Other packages.** Calls into another package of the same repository
  resolve to its built type files, and only after a build (C38). The
  helper therefore points the compiler's `paths` option (C39) at each
  workspace package's source, which resolved to source with no build
  (C40).
- **Reuse.** `groundwork_config` provides the project root, the directory
  skip list and file walking (C1). The merge-base diff logic, now written
  twice (C2), moves into it as a shared helper. The tests use the existing
  temporary-repository harness.

### Option B: one language-server client for both languages

Everything goes through the Language Server Protocol, the same channel
editors use. A Python client starts `typescript-language-server` and a
Python language server (jedi-language-server or pyright's server).
`documentSymbol` gives the boxes; `references` and `definition` give the
arrows.

**Its strongest case:**
- One protocol for every language. Adding Go or Rust later means adding a
  server, not writing new resolver code.
- Each server already handles project configuration, workspace packages
  and incremental indexing, which Option A has to arrange itself (the
  `paths` mapping above).
- No tree-sitter dependency.

### Option C: tree-sitter only, no resolver

The smallest change: one Python program and the tree-sitter wheels (C5,
C6), with no Node and no jedi.
- Solid arrows only where syntax alone decides: a call to a name defined
  once in the same file, or imported by name from a relative module path
  that resolves to one file.
- Everything else is dashed.

**Its strongest case:**
- The fewest moving parts and the fastest run (C10).
- Nothing in the comment can come from a resolver bug.

## Comparison

| | A: tree-sitter + resolvers | B: language servers | C: tree-sitter only |
|---|---|---|---|
| Work for callers | One command, `pr_map.py --base <ref>` | Same | Same |
| Reuses existing code | `groundwork_config`, test harness; resolvers used through their documented APIs (C36, C41) | Same Python parts; nothing for the protocol | Same Python parts |
| New code and abstractions | Constructs, graph, renderer, poster; a Node helper (one function, about 100 lines); a `paths` mapping | A JSON-RPC client with server start-up, initialization and indexing waits, plus per-server quirks | Constructs, graph, renderer, poster; a syntactic import resolver |
| Fits project rules | Rule 10 needs the program kept apart from the stdlib-only scripts (see the rules check) | Same, plus two servers to install and pin | Closest to rule 10, but still needs the tree-sitter wheels |
| Risk and unknowns | jedi may stop early on hard code (C24), so its silence cannot be read as "no callers". The TypeScript 7 API change (C15, unverified) is avoided by pinning TypeScript 5.9.3 | Whether pyright's server gives references is unverified: research covered only its command line (C18). Start-up time unmeasured | Low technical risk |
| Criteria it cannot meet | None | None, if the servers behave as assumed | None by the letter, but every ambiguous TypeScript call is dashed. That is 26% of calls that match a repository name (C12). The resolver calls A relies on gave the exact definition in every case measured (C37, C40, C42), though none of those was one of the most duplicated names |

## Decision

**Option A.**
- **Why not B:** A meets every criterion with the least new machinery. Its
  only resolver interface is one documented call per language (C36, C41),
  each measured on this repository's own code (C37, C40, C42). B's
  uniformity would help with more languages, but no criterion asks for
  more than TypeScript and Python (AC-9). B also rests on an unmeasured
  and partly unverified server set-up.
- **Why not C:** C is simpler, but it gives up exact arrows for a quarter
  of TypeScript calls. In the requirements interview on 2026-10-07 the
  owner chose "exact, or flagged": solid wherever the language's tooling
  can confirm a reference.

## Rejected options

- **B, language servers.** A protocol client and two servers to install,
  start and wait on, for an extensibility no criterion needs (rule 2).
  Its Python references depend on a server capability research did not
  verify (C18 covers only pyright's command line). Revisit when a third
  language is requested.
- **C, tree-sitter only.** It meets the criteria's letter by drawing
  ambiguous TypeScript calls dashed. The owner asked for solid arrows
  wherever the language's tooling can confirm one, and A shows it can
  (C37, C40).

## Design

### Where the code lives

pr-map needs installed packages, so it lives apart from the stdlib-only
checks (rule 10), in `scripts/pr_map/`:

| File | Responsibility |
|---|---|
| `pr_map.py` | Entry point and pipeline: base ref, changed files, graph, rendering, posting |
| `constructs.py` | tree-sitter parsing; finding constructs and call sites; byte-to-character column conversion |
| `queries/typescript.scm`, `queries/python.scm` | Tags-style queries. Adapted from the tree-sitter grammars and Etchpad's fork (MIT), with a credit header |
| `resolve.py` | `definition_at(path, line, column)` for both languages: jedi in-process, and the Node helper for TypeScript |
| `resolve_ts.cjs` | Node helper: reads requests line by line on stdin and writes answers on stdout |
| `render.py` | Mermaid diagrams, splitting, the text list, the comment body |
| `github.py` | Upserting the comment through the REST API (standard library `urllib`); writing the job summary |
| `requirements.txt` | Pinned: tree-sitter 0.26.0, tree-sitter-python 0.25.0, tree-sitter-typescript 0.23.2, jedi 0.20.0 (C5, C6, C17) |
| `package.json`, `package-lock.json` | Pinned typescript 5.9.3, the version measured (C14, C36) |

`groundwork_config.py` gains `merge_base(root, base)` and
`diff_against(root, base, *args)`. `detect_workarounds.py` and
`check_ac_coverage.py` switch to them, which removes the duplication
research found (C2). They stay standard library only.

### Data model

One representation (rule 4), also written as JSON with `--json` for tests
and for version 2's AI overlay:

```python
@dataclass(frozen=True)
class Box:
    id: str  # "<path>::<qualified name>", plus "#2", "#3" for repeats in one file
    kind: str  # "function" | "method" | "class" | "member" | "module"
    name: str  # qualified: "Class.method", "outer.inner"
    path: str  # relative to the repository root
    line: int  # 1-based line of the name
    column: int  # 0-based character column of the name
    status: str  # "changed" | "added" | "removed" | "neighbour"


@dataclass(frozen=True)
class Arrow:
    source: str  # Box.id of the innermost construct containing the reference
    target: str  # Box.id of the construct referred to
    certainty: str  # "exact" | "possible"
    at: str  # "<path>:<line>:<column>" of the reference site
    reason: str  # for "possible": "unresolved", "through <box>", "resolver failed: <why>"
```

- **`member`** covers what has a name and a body or type but is not a
  function or class: interface and abstract method signatures, property
  signatures, and class fields that hold an arrow function. The queries
  capture `method_signature`, `abstract_method_signature`,
  `property_signature` and `public_field_definition` for TypeScript.
- **Repeated names in one file** get `#2`, `#3` in source order. Examples
  are a Python `@property` getter and its setter, or a function defined
  in both branches of an `if`. Classification pairs them by ordinal, so
  inserting a new repeat above an old one can show as one changed box
  plus one added box; the arrows stay right.
- **A reference at module level**, outside any construct, gets a `module`
  box named after its file, so a top-level caller is not lost.

### Pipeline

1. **Base and files.**
   - `base = merge_base(root, "origin/<base branch>")`.
   - Changed files come from `diff_against(root, base, "--name-status",
     "-M")`, filtered to `.ts`, `.tsx` and `.py` outside the skip list.
     `-M` pairs renamed files.
2. **Constructs.** Constructs are needed for every source file in the
   head tree, not only the changed ones: a callee's answer or a related
   box is matched by its name position anywhere in the repository. The
   whole-repository scan took under 0.3 s (C10, C10b), and its result is
   reused for the name matches in step 5.
   - Each changed file is parsed at both commits: the head version from
     the working tree, the base version from `git show <base>:<path>`.
   - A construct's identity is its path, qualified name and, for repeats,
     its ordinal (see the data model).
3. **Classify** (AC-1 to AC-3, AC-10). Hunk line ranges come from
   `diff_against(root, base, "-U0", "--", path)`.
   - **changed:** the construct is in both commits, and its head span
     overlaps an added line or its base span overlaps a deleted line. A
     signature change counts, because the signature is inside the span.
   - **added:** in head only.
   - **removed:** in base only.
   - A renamed or moved construct shows as removed plus added. No
     criterion asks for rename detection.
4. **Nesting.** Constructs nest: a method sits inside a class, a function
   inside a function. Every line and every reference site belongs to its
   *innermost* construct only.
   - A changed line inside method `C.m` changes `C.m`, not class `C`. `C`
     is changed only by lines outside all of its nested constructs, such
     as its heritage clause or a field.
   - The source of an arrow is the innermost construct containing the
     reference.
   - So one edit produces one changed box, and every arrow is drawn once.
5. **Candidates.** A candidate is a place in the code that may refer to a
   box. There are three sources, and the candidates are their union:
   - **Name matches from tree-sitter.** Every identifier whose text
     equals a box's *match key*.
     - **The match key** is the last segment of the box's name (`m` for
       `C.m`).
     - **Constructors.** A constructor (`__init__` and `__new__` in
       Python, `constructor` in TypeScript) uses its class's name as its
       match key, because a call reads `Foo(1)` or `new Foo(1)`, never
       `__init__`. jedi's reference search does not find those calls
       either (C50). In Python, the names of subclasses that define no
       `__init__` or `__new__` of their own are match keys too, followed
       down the hierarchy, because `Baz(3)` runs `Foo.__init__` when
       `Baz(Foo)` does not override it. Each subclass's base names are
       resolved with `goto` (C41). TypeScript's `findReferences` on the
       constructor already finds `new Baz(3)` and `super(…)`.
     - **Python calls on the runtime class.** `cls(…)` inside a
       classmethod and `type(self)(…)` inside a method of the class or a
       subclass are candidates for its constructor. Which class runs is
       decided at run time, so they are possible arrows, reason "through
       `cls`".
     - **Node kinds.** In TypeScript the kinds are `identifier`,
       `property_identifier`, `shorthand_property_identifier` and
       `type_identifier`, the last so that type-only uses (`x: R`,
       `implements R`) of a removed class are found. In Python they are
       identifiers and attribute names.

     This covers calls, but also functions passed as values
     (`.action(runX)`, `key=fn`, `{ run: cmdRun }`). Scanning the whole
     repository took under 0.3 s (C10, C10b).
   - **The resolver's reference search**, for each changed or added box:
     - TypeScript `findReferences` (C13). It follows renamed imports,
       default imports under another name, calls made through an
       interface two levels above the box, constructors called with
       `new`, and methods of object literals typed by an interface (C43,
       C44, C45, C53, C54).
     - jedi `get_references` (C16, C17b). It finds a renamed import but
       not the calls through it (C46), so pr-map follows aliases itself
       (next point).
   - **Aliases.** When a reference site from either source is the name in
     an import that renames it (`as save`, `{ readClip as rc }`), the new
     name's identifiers in that file become candidates too.

   Candidates, by role:
   - **Callers of a changed or added box:** all three sources.
   - **Callees of a changed or added box:** identifiers inside its own
     span.
   - **Callers of a removed box:** name matches and aliases in the head
     commit. The resolver cannot search for a definition that no longer
     exists.
6. **Verdicts** (AC-4 to AC-7). `definition_at(path, line, column)`
   answers each candidate with a list of locations. Each location has a
   file, line and column; TypeScript answers also carry their
   `DefinitionInfo.kind`.
   - **A location is a box** only when its line *and* column are the
     name position of a construct the tags query found. A parameter or a
     local declared on the same line as a function's name is therefore
     never mistaken for the function.
   - **Overloads are one box.** TypeScript overload signatures are sibling
     declarations, and a call resolves to the one signature it matches
     (C55). The constructs step therefore groups adjacent same-name
     signatures with their implementation into one box, and a location
     at any of their names is that box.
   - **A class with its constructor.** A call of a class resolves to the
     class in Python (C51), and to both the class and its constructor in
     TypeScript (C52). Only a real call counts as a call of the
     constructor:
     - **TypeScript:** the answer counts as the constructor box only when
       it includes the constructor's own location. `new Foo` and
       `super(…)` do; a type annotation or `Foo.make()` answers with the
       class alone and counts as the class.
     - **Python:** a class answer counts as `__init__` or `__new__` only
       when the identifier is the function of a call node (`Foo(1)`,
       `Baz(3)` for a subclass without its own constructor). An
       annotation, `Foo.make()` and `isinstance(x, Foo)` count as the
       class.
     - **Removed constructors** never match a class answer: the call no
       longer runs them.
     - **A callee `new Foo()`** is one arrow, to the constructor box
       when the class defines one, else to the class box.
   - **Library calls are recognised before anything is drawn.** Without
     the project's dependencies, a library call does not resolve to the
     library: jedi answers nothing (C56) and TypeScript answers the import
     line in the calling file (C57). So before an empty or import-only
     answer becomes a dashed arrow, the candidate's name is traced to its
     import, using the leftmost name for an attribute chain (`np` in
     `np.mean`). The import is a library import when its module is not in
     the repository:
     - **Python:** a top-level module that is not found under the
       repository's project roots;
     - **TypeScript:** a bare specifier that is neither a workspace
       package nor a key of the project's `paths`.

     When the leftmost name is a local variable instead of an import, its
     initial value is traced the same way: `const program = new
     Command()` or `arr = np.array(xs)` makes `program.action(...)` and
     `arr.mean()` library calls. This follows one assignment in the same
     scope. A variable assigned more than once, or a parameter, is not
     traced, and its calls stay as unresolved.

     A library call draws no arrow. The text section counts library calls
     per file, so nothing disappears silently.
   - **Related box:** another box is related to the target T when one of
     these holds:
     - **TypeScript:** the candidate came from T's own `findReferences`.
       The compiler links it to T through renames, interfaces, base
       classes and typed object literals (C43 to C45, C54).
     - **TypeScript, structural:** T is a method, and the box is an
       interface method signature, or a property signature with a
       function type, with T's name. TypeScript matches classes to
       interfaces by shape, so a class with no `implements` clause can
       still be called through the interface, and `findReferences` on T
       would not link them. A plain data property with T's name is not
       related: `c.notes` on `interface Clip { notes: number[] }` says
       nothing about a function `notes()`.
     - **Python:** the box is a member with T's name in a class that T's
       class inherits from, directly or further up. Each base-class name
       is resolved with `goto` (C41), not matched by text. The same holds
       for a member of a `Protocol` class with T's name, since a protocol
       is matched by shape, not by inheritance.

   | Answer | Caller candidate for box T | Callee candidate | Removed box R |
   |---|---|---|---|
   | T | exact arrow | exact arrow (T calls itself) | not possible (R is gone) |
   | A related box | possible arrow, reason "through `<that box>`" | exact arrow to that box | no arrow |
   | Another box, unrelated | no arrow | exact arrow to that box | no arrow |
   | A local variable or parameter | no arrow | no arrow | no arrow |
   | Another repository definition that is not a box (an attribute set in `__init__`, an untyped object's property) | no arrow; the site is listed in the text section as "refers to `<path:line>`" | same | no arrow |
   | A definition outside the repository (library, standard library) | no arrow | no arrow: boxes are constructs in the repository | no arrow |
   | A library import (traced as above) | no arrow, counted as a library call | no arrow, counted as a library call | no arrow |
   | An import of a repository module that did not resolve | possible arrow, reason "unresolved import" | possible arrow, only when exactly one repository box has that name; otherwise listed as an unresolved call without arrows | possible arrow, reason "unresolved" |
   | Nothing, or several unrelated boxes, and the name is not a library import | possible arrow | as for an unresolved import | possible arrow, reason "unresolved" |
   | Resolver failed | possible arrow, reason "resolver failed: …" | as for an unresolved import | same |

   What this guarantees:
   - **A solid arrow** is always a resolver answer whose location is that
     exact box's name position (AC-5).
   - **A dashed arrow** is always a real reference site whose name, or
     alias, matches its target, and whose target the resolver could not
     rule out (AC-6, AC-7).
   - **A caller is dropped from the diagram only** when the resolver names
     a local or a box unrelated to the target, or a definition that is not
     a box (listed in the text), or when its name traces to a library
     import (counted). A relation through a rename, an interface method, a
     base class or a protocol keeps it as a dashed arrow. Real flows of a
     function through a property (`{ run }`, `{ run: cmdRun }`) are still
     found: by `findReferences` in TypeScript, and in both languages by
     the name match where the function is assigned.
   - **A library call never draws an arrow** to a same-named repository
     function, so `np.mean(xs)` does not point at the repository's own
     `mean` (AC-7).
   - **jedi stopping early (C24)** cannot drop a caller: name matches and
     aliases still produce the candidate.

   An unresolved callee with several possible repository targets is
   listed in the text section rather than fanned out to every same-named
   box. So `d.get()` on an untyped value does not draw an arrow to every
   `get` in the repository.
7. **Resolvers.**
   - **Python.** One `jedi.Project` per nearest directory with
     `pyproject.toml`, `setup.cfg` or `setup.py`, else the repository
     root. `Script.goto(line, column, follow_imports=True)` (C41), and
     `get_references` (C17b). Columns are converted from tree-sitter's
     bytes to characters. jedi answers carry line and column.
   - **TypeScript.** `resolve_ts.cjs` loads the pinned typescript and
     keeps one LanguageService per nearest `tsconfig.json` (default
     options when there is none).
     - A file the tsconfig does not include, such as a test directory
       outside `include`, is added to that LanguageService's root files
       when it is queried, so its references resolve.
     - Its compiler options add `paths` entries for each workspace
       package: the `name` in its `package.json`, mapped from the `types`
       entry under the package's `outDir` to the same path under its
       `rootDir` (C38 to C40). The project's own `paths` win when both
       name a package.
     - Protocol: one JSON object per line. Requests are
       `{"id", "op": "definition" | "references", "file", "line",
       "column"}`, with columns in UTF-16 code units, converted in
       Python. Answers are `{"id", "locations": [{"file", "line",
       "column", "kind"}]}` or `{"id", "error"}`.
     - If Node or the helper is missing, or the helper dies, the
       TypeScript candidates fall back to possible arrows with that
       reason. The comment says so, and a warning is logged. This is the
       only fallback, and it is tested in both directions.
8. **Render** (AC-8, AC-10 to AC-13, AC-17, AC-19).
   - **Header:** "Computed from `<base short sha>` (base) to `<head short
     sha>` (head)."
   - **No constructs:** "No function-level changes to map".
   - **One Mermaid `flowchart LR`**, as the requirements describe, until
     it would exceed the budget below.
     - Box labels show the name and `path:line`.
     - Status shows in the label text ("changed: run"), so it does not
       depend on colour; a class adds colour.
     - Exact arrows are `-->`; possible ones are `-.->|possible|`.
   - **Splitting.** GitHub states no Mermaid limit of its own (C29) and
     Mermaid defaults to 50,000 characters and 500 edges (C27, C28). Each
     diagram therefore stays under 45,000 characters and 450 arrows.
     - Over budget, the map first splits into one diagram per connected
       group of boxes (AC-12).
     - A group still over budget splits into one diagram per changed,
       added or removed box with its arrows.
     - A single box over budget splits its arrows into numbered parts.
     - A box may appear in several diagrams. Every box and arrow appears
       in at least one, which a test checks.
   - **Text list.** A collapsed `<details>` table of every arrow (from,
     to, exact or possible, call site), every box without arrows, and
     every unresolved call with its count of possible repository
     targets.
   - **Notes.**
     - Files that could not be read are listed with the reason.
     - Files with syntax errors are mapped from the parts that parse
       (C8, C11) and listed with their error lines.
9. **Post** (AC-14 to AC-18).
   - **Finding the comment.** The comment carries the marker
     `<!-- groundwork:pr-map -->`. The poster pages through the pull
     request's issue comments and edits the one that has the marker *and*
     was written by `github-actions[bot]`, or creates one. The pull
     request number comes from `GITHUB_EVENT_PATH`.
   - **Where the complete map lives.** It always goes to two places:
     - the job summary (`GITHUB_STEP_SUMMARY`), limited to 1 MiB per step
       (C31);
     - a workflow artifact named `pr-map`, holding the Markdown and the
       JSON, which has no such limit.

     If the map is over 1 MiB, the summary says so and points to the
     artifact. Either way the complete map is always one link away
     (AC-11, AC-14).
   - **Fork, or a 403 from the API.** The token is read-only on forks
     (C33), so there is no comment; the summary says why (AC-18).
   - **422 from the API.** The comment length limit is undocumented
     (C30), so the poster reacts to a rejection instead of assuming a
     number. It retries with smaller bodies, in this order:
     1. move the text list out of the comment;
     2. move diagrams out, last first, one per retry.

     Each version says how much moved to the run page and links it
     (`GITHUB_SERVER_URL`, `GITHUB_REPOSITORY`, `GITHUB_RUN_ID`) (AC-14).
     The last version is the header, the counts and the link. If even
     that is rejected, the poster stops, and the summary records the
     API's response. The check still passes (AC-21).
10. **Failure** (AC-19 to AC-21).
   - Each stage wraps its errors with what it was doing ("resolving
     TypeScript references in <file>"), keeping the cause (rule 7).
   - The entry point catches anything left, posts "pr-map could not build
     the map: <error>" as the comment and summary, and exits 0.
   - Without `--post` (a contributor running it locally), a missing
     `--base` or git exits 2. With `--post` it posts the problem and
     exits 0, like any other failure (AC-20, AC-21).
   - In the workflow, the install and upload steps use
     `continue-on-error` (C47), and `pr_map.py` reports a missing package
     in the comment. See the workflow template below (AC-21).

### Workflow template: `templates/ci/pr-map.yml`

- Trigger: `pull_request`.
- Permissions: `contents: read`, `pull-requests: write`.
- Concurrency: group `pr-map-${{ github.event.pull_request.number }}`
  with `cancel-in-progress: false`.
  - At most one run per pull request is in progress at a time, so a
    second run always finds and edits the first run's comment. Two quick
    pushes cannot create two comments (AC-16).
  - A newer run cancels one that is still pending (C48). That run's check
    shows as cancelled, not failed, and the newest run still posts the
    up-to-date map.
- Steps, each action pinned to a commit SHA (rule 12):
  1. `actions/checkout`, the pin already in `templates/ci/groundwork.yml`,
     with `fetch-depth: 0` and `ref: ${{ github.event.pull_request.head.sha }}`.
     That checks out the pull request's own head commit instead of
     GitHub's merge commit (C49), so the header's head SHA is a commit on
     the pull request (AC-17);
  2. `actions/setup-python`, the pin already in `.github/workflows/ci.yml`,
     Python 3.12;
  3. `actions/setup-node` v7.0.0 at `820762786026740c76f36085b0efc47a31fe5020`,
     the commit `git ls-remote` reports for the tag (and the pin
     ableton-workflow-helper's CI uses), Node 22;
  4. `pip install -r .groundwork/bin/pr_map/requirements.txt`;
  5. `npm ci --prefix .groundwork/bin/pr_map`;
  6. `python .groundwork/bin/pr_map/pr_map.py --base "origin/${{ github.base_ref }}" --post`;
  7. `actions/upload-artifact`, uploading the `pr-map` artifact. The pin
     comes from the action's release tags when the template is written
     (the latest tag on 2026-10-07 was v7.0.2).
- Every step after checkout (steps 2 to 7) sets `continue-on-error: true`,
  which keeps the job from failing when that step fails (C47). That
  includes step 6, so a crash before `pr_map.py`'s own top-level catch
  cannot fail the check either. Checkout is the one step left without
  it: without the code there is nothing to map, and a failed checkout is
  a repository problem, not the map's.
- Hangs: each request to the TypeScript helper has a time limit. A helper
  that does not answer is stopped and treated as failed, which is the
  fallback above. No job-level timeout is used: whether a timed-out job
  counts as a failed check is not something research checked.
  - An install failure leaves pr-map to report the missing package in the
    comment.
  - An upload failure loses only the artifact; the comment and the
    summary still say where the map is.
  - So the map never fails the pull request's checks (AC-21).
- The project's own dependencies are not installed. Calls into libraries
  are not drawn anyway, and repository code resolves without them (C40).

### Tests

- **Location.** `tests_pr_map/`, a separate directory with its own CI job
  that installs `requirements.txt` and runs `npm ci`. The stdlib-only
  tests keep running without the packages (rule 10).
- **Fixture repositories**, built with the existing temporary-repository
  harness. The TypeScript fixture has two workspace packages and
  same-named functions; the Python fixture has same-named functions and a
  call through an alias.
  - Each fixture has a hand-written list of its references: each site
    with its true target, or "uncertain" where the code itself does not
    decide (an untyped parameter). Every arrow on the map is checked
    against it (AC-7):
    - **an exact arrow** must match a site and its true target;
    - **a possible arrow** must match a site whose true target is that
      box, or one marked "uncertain" whose name is that box's.
  - The fixtures also cover each case the verdicts distinguish:
    - renamed and default imports, in both languages;
    - a function passed as a value;
    - a call through an interface two levels up, an object literal typed
      by an interface, a Python base class two levels up, and a
      `Protocol`;
    - a parameter declared on its function's name line and then called;
    - a local variable, and an unresolved import of a repository module;
    - a library import whose name equals a repository function
      (`np.mean` next to a repository `mean`), with the library not
      installed;
    - constructors in both languages, called as `Foo(1)` and `new Foo(1)`,
      through a Python subclass without its own `__init__`, and next to
      non-calls of the class: an annotation, `Foo.make()` and
      `isinstance(x, Foo)`;
    - a function next to a same-named interface data property and an
      untyped object key (`notes()` beside `c.notes`);
    - library objects held in a variable (`program = new Command()`,
      `arr = np.array(xs)`) whose methods share names with repository
      functions;
    - `cls(…)` and `type(self)(…)` in Python;
    - a TypeScript class with no `implements` clause called through an
      interface;
    - a removed class referred to only in types;
    - nested constructs, overloads, and repeated names in one file;
    - a test file outside its tsconfig's `include`.
- **GitHub API.** A local HTTP server implements the issue comment
  endpoints, with modes for 403 and 422. It fakes a process boundary
  (rule 5); no mocks.

## Criteria coverage

| Criterion | How the design meets it |
|---|---|
| AC-1 | Classify: changed, head span overlaps added lines or base span overlaps deleted lines; signatures inside the span |
| AC-2 | Classify: added, in head only |
| AC-3 | Classify: removed; callers by name in head, with verdicts (table, last column) |
| AC-4 | Candidates from names and the resolver's reference search, one step each way; innermost construct as source |
| AC-5 | Exact only on a resolver answer naming the box (verdict table) |
| AC-6 | Possible on nothing, several or resolver failure, with the reason |
| AC-7 | Arrows exist only at real reference sites; fixture tests check every arrow, exact and possible, against a hand-written list |
| AC-8 | Box label shows the qualified name and `path:line` |
| AC-9 | `.ts`, `.tsx`, `.py` with both queries and resolvers; a mixed fixture |
| AC-10 | "No function-level changes to map" |
| AC-11 | No cap anywhere in the pipeline |
| AC-12 | Splitting by group, then by box, then by part, under 45,000 characters and 450 arrows |
| AC-13 | Collapsed text table of every arrow and box |
| AC-14 | 422 retries with smaller bodies and a link; the complete map always in the summary or artifact |
| AC-15 | Workflow on `pull_request` (opened and new commits) |
| AC-16 | Marker comment by `github-actions[bot]`, edited in place; runs on one pull request queue |
| AC-17 | Header with the merge-base and pull request head short SHAs; the workflow checks out the head commit (C49) |
| AC-18 | Fork or 403: job summary only, with the reason |
| AC-19 | Unreadable files listed; files with syntax errors mapped partially and listed |
| AC-20 | Top-level catch posts the error |
| AC-21 | Exit 0 on map failures; `continue-on-error` on every step after checkout (C47); a time limit on helper requests |
| AC-22 | Deferred, as the requirements say. Setup gains a copy of `scripts/pr_map/` and the template after the trial in one project |

## Project rules check

1. **Reuse before building:**
   - `groundwork_config` (root, skip list, file walking);
   - the temporary-repository test harness;
   - the merge-base diff helper, consolidated rather than written a third
     time (C2).
2. **Simplest design:** one entry point and two options (`--base`,
   `--post`), plus `--json` for tests. No language-server layer, no
   plugin system for languages.
3. **Libraries directly:** tree-sitter queries, jedi `goto` and the
   LanguageService are called as documented. `definition_at` is a single
   function per language, not a wrapper library. It exists so the verdict
   table has one source of answers.
4. **One representation:** `Box` and `Arrow`. The JSON output is the same
   data, serialized.
5. **Tests from criteria:** fixture repositories and a local HTTP server.
   No mocks of the unit under test.
6. **Never weaken a check:** no skips. The one fallback (TypeScript
   resolver missing) is commented, logged as a warning and tested both
   ways.
7. **Errors are specific:**
   - a resolver failure is a reason on the arrow, not a missing arrow;
   - API failures are told apart by status (403 versus 422);
   - wrapped errors keep their cause.
8. **Sources:** every factual claim above cites research. GitHub's own
   Mermaid and comment limits are unverified (C29, C30), and the design
   works around both instead of assuming numbers.
9. **Evidence before claims:** the measured behaviours behind the decision
   (C37, C40, C42) come from scripts kept in `spike/`.
10. **Scripts run anywhere (exception, with reason):** pr-map needs
    installed packages. As the rule requires, it lives apart
    (`scripts/pr_map/`, its own requirements, workflow and test job). The
    stdlib-only scripts do not import it, and still run without it.
11. **CI does not need the plugin:** the workflow runs the copy in
    `.groundwork/bin/pr_map/`.
12. **Actions pinned:** checkout and setup-python reuse this repository's
    pins; setup-node and upload-artifact are pinned to the commits their
    release tags resolve to.
