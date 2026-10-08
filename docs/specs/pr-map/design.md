# Design: pr-map

- Status: revision 1 approved (2026-10-08, by the owner; five fresh-context reviews, the last round of fixes not re-reviewed by the owner's choice). Revision 2 ("Revision 2" at the end) awaiting review
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
       either (C50).
     - **Python subclasses.** `Baz(3)` runs `Foo.__init__` when `Baz`
       does not get an `__init__` from somewhere else first. pr-map
       builds each class's method resolution order from its base names,
       each resolved with `goto` (C41), using Python's C3 linearization.
       A constructor box's *runners* are the classes whose order reaches
       T's class before any other class defining that method. A mixin
       listed before `Foo` that defines `__init__` takes the class out of
       the set; so does a subclass with its own `__init__`. The runners'
       names are match keys.
     - **The method's own name** (`__init__`, `__new__`) is a match key
       too, so `super().__init__(…)` and `Foo.__init__(self, …)` are
       found by tree-sitter even if jedi stops early (C24).
     - TypeScript's `findReferences` on a constructor finds `new this`,
       `super(…)` and calls of a subclass without its own constructor
       (C62).
     - **Python calls on the runtime class.** `cls(…)` inside a
       classmethod and `type(self)(…)` inside a method of one of the
       constructor's runners are candidates for it. Which class runs is
       decided at run time, so they are possible arrows, reason "through
       `cls`".
     - **TypeScript `super` and `this`.** `super(…)` and `new this(…)`
       are parsed as `super` and `this` nodes, not identifiers. Inside a
       changed or added box they are callee candidates;
       `getDefinitionAtPosition` answers the constructor they run (C61).
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
   - **Import lines are not reference sites.** An import statement draws
     no arrow: the uses in code do. A function imported but never used
     is left to the project's linter (ruff's F401, oxlint), which already
     reports unused imports. Decided by the owner, 2026-10-08. Imports
     still matter for two things: following aliases (next point) and
     recognising library calls.
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
       when the identifier is the function of a call node, and the class
       is T's class or one of T's runners (`Foo(1)`, `Baz(3)`). An
       annotation, `Foo.make()` and `isinstance(x, Foo)` count as the
       class.
     - **Each answer is read against the target it is a candidate for.**
       When T is the class box, a class answer, or TypeScript's class and
       constructor pair, counts as T. So a class changed by a field still
       gets its `Foo(1)` and `new Foo(1)` callers. When T is the
       constructor box, the rules above apply. When both changed, the
       call is an arrow to each.
     - **Removed constructors** never match a class answer: the call no
       longer runs them. The calls are listed in the text section as
       "called `Foo(…)`, whose `__init__` was removed", because they may
       now pass the wrong arguments.
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
     scope. A parameter whose type annotation names a library import
     (`cmd: Command`) is traced through that import. A variable assigned
     more than once, or an untyped parameter, is not traced, and its
     calls stay as unresolved.

     A library call draws no arrow. The text section counts library calls
     per file, so nothing disappears silently.
   - **Related box:** another box is related to the target T when one of
     these holds:
     - **TypeScript:** the candidate came from T's own `findReferences`.
       The compiler links it to T through renames, interfaces, base
       classes and typed object literals (C43 to C45, C54).
     - **TypeScript, structural:** T is a method, and the box is an
       interface method signature, or a property signature with a
       function type, with T's name, *and* the type checker reports T's
       class assignable to that interface (`isTypeAssignableTo`, C63).
       TypeScript matches classes to interfaces by shape, so a class with
       no `implements` clause can still be called through the interface,
       and `findReferences` on T would not link them. A same-named method
       on an incompatible interface is not related (C64). A plain data
       property with T's name is not related either: `c.notes` on
       `interface Clip { notes: number[] }` says nothing about a function
       `notes()`. The helper gains one request kind for the check.
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
     `get_references` (C17b).
     - **No inferred parameter types.** jedi infers an untyped
       parameter's type from the calls it sees, which is on by default
       (C58, C59). With it on, `obj.save()` on an untyped parameter
       answered one class's method although two classes are passed in. A
       guess like that would become a solid arrow, and the other class's
       caller would vanish. pr-map turns both settings off, so the answer
       is empty (C60) and the call is a possible arrow, as AC-6 says. Columns are converted from tree-sitter's
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
       "column"}` (and `"op": "assignable"` with two locations), with
       columns in UTF-16 code units, converted in
       Python. Answers are `{"id", "locations": [{"file", "line",
       "column", "kind"}]}` or `{"id", "error"}`.
     - If Node or the helper is missing, or the helper dies, the
       TypeScript candidates fall back to possible arrows with that
       reason. The comment says so, and a warning is logged. This is the
       only fallback, and it is tested in both directions.
8. **Render** (AC-8, AC-10 to AC-13, AC-17, AC-19).
   *Replaced by "Revision 2" below; kept for the history of splitting.*
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
    - a Python class with a mixin before its base, and a subclass with
      its own `__init__`;
    - an untyped Python parameter passed two different classes;
    - a class changed by a field, called as `Foo(1)` and `new Foo(1)`;
    - TypeScript `super(…)` and `new this(…)` inside a changed
      constructor;
    - a same-named method on an incompatible TypeScript interface;
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

## Revision 2: file map and file sections

Requirements revision 2 (2026-10-08) changes how the map is laid out, not
how it is computed. Steps 1 to 7 of the pipeline stay as they are, except
that `.groundwork/` is left out (AC-30). Step 8 is replaced.

### Context

The trial (`trial.md`) drew one diagram of 180 boxes. The owner read it on
a phone in dark mode and found three problems:

- **It was too big.** The canvas was 5,316 by 13,888 pixels. 152 of the
  180 boxes came from `.groundwork/`, which holds copies of this plugin's
  scripts, not the project's code.
- **Dark mode was unreadable.** The dark theme sets light text, and the
  status classes forced light fills, so changed and added boxes had light
  text on a light fill (`spike/trial-map-excerpt.txt`).
- **Escape codes showed.** `merge_base` displayed as `merge&#95;base`.
  The client drew labels as SVG text, which does not decode
  Mermaid's entity codes (C65, C66).

### Options

#### Option R1: the layout is a view, computed in `render.py`

`build_map` keeps producing boxes and arrows. It adds only what the
renderer cannot know: each changed file's diff status (`files`). `render.py`
groups boxes by path for the file map, and picks each changed file's boxes
and the arrows touching them for its section.

- Every box and arrow still has one source: the function map. File arrows
  are counts over it, made when the comment is written.
- The JSON stays the same apart from `files`, so the locked graph tests
  and version 2's overlay are unaffected.
- The renderer grows: grouping, sections and the AC-27 collapse all live
  in it.

#### Option R2: the file level is part of the map's data

`build_map` also returns `file_boxes` and `file_arrows` (path, status,
counts, certainty), and each box carries its section. `render.py` only
draws.

- At its strongest: the file level becomes testable from the JSON without
  parsing Markdown, version 2's overlay can cite file arrows directly, and
  the renderer stays a printer.
- The JSON gains a second, derived copy of the arrows. Every change to the
  graph has to keep both in step, which is what project rule 4 forbids.

### Comparison

| | R1: view in the renderer | R2: file level in the data |
|---|---|---|
| Work left to callers | None: `render_comment(map, run_url)` as today | None |
| New representations | `files`: the diff status per changed file, which the map does not hold yet | `files`, plus file boxes and file arrows derived from the arrows (rule 4) |
| Tests | Rendered comment, as today's render tests do | JSON for the file level, comment for the layout |
| Size and risk | `render.py` grows; `pr_map.py` adds one field | Both grow; the JSON format changes for version 2 |

### Decision

**R1.** It meets every criterion with one new field and no copy of the
arrows. The file level is a way of drawing the arrows, not a fact about
the code, so it belongs where drawing happens. R2's testability gain is
small: the render tests already read the comment.

**Rejected: R2.** A second representation of the arrows (rule 4), for a
benefit no criterion asks for. Revisit if version 2 needs file arrows in
the JSON; they can be computed from the arrows then.

### Step 0: check on GitHub before the build

Two facts decide whether this layout works, and neither can be measured
outside GitHub:

- **Collapsed sections.** Mermaid run inside a closed `<details>` draws an
  empty diagram that stays empty when opened (C78). A 2022 report says
  GitHub fails the same way when an arrow has a label (C79), and section
  diagrams have `possible` labels (AC-6).
- **The mermaid version** github.com runs (C74), which decides whether
  the labels above are exact.

A test comment on the trial pull request (ableton-workflow-helper #33)
holds an `info` diagram, the labels and outlines above, and two collapsed
sections, with and without an arrow label. The owner checks it in a
desktop browser, a phone browser and the app used for the trial.

- **If collapsed diagrams render when opened:** build as designed.
- **If they do not:** the sections cannot be collapsed and still show
  diagrams. AC-25 goes back to the owner. The choices are open sections
  under a heading, or collapsed sections with the diagram above the
  `<details>`.
- **If GitHub runs mermaid 11.12 or older:** the label rule changes before
  the build, and the measurements are rerun for that version.

### Changes to the pipeline

**Step 1, base and files** (AC-30).
- `.groundwork/` is left out with the other skipped paths: changed files
  under it are not parsed, and the whole-repository scan in step 2 does not
  read it, so its functions are neither boxes nor neighbours.
- The count of changed source files left out this way goes in the notes
  as `left_out: {".groundwork/": n}`.
- The prefix is a constant in `pr_map.py`, applied in `_source()` (changed
  files) and to the result of `constructs.scan` in `build_map` (the
  whole-repository scan), which cannot import `pr_map.py`, including its
  list of unreadable files, so they are not reported as skipped. `SKIP_DIRS` in
  `groundwork_config.py` is not changed, because the other checks that use
  it are outside this revision.
- The resolvers still see `.groundwork/`. A resolver answer that lands
  there is a definition that is not a box, so it is listed in the text
  section as "refers to", like any other (step 6). Project code rarely
  imports those scripts.

**The map gains `files`**: `{path: "changed" | "added" | "removed"}` for
each changed source file, from the `FileChange(old, new)` pairs after
`_source()` has filtered them, not from the raw status letters:
- `old` absent: the new path is "added";
- `new` absent: the old path is "removed";
- both present and equal: "changed";
- a rename: the new path is "changed" and the old path "removed", because
  the constructs that only the base had are removed boxes under the old
  path (`classify()` parses the base at `change.old`). A rename to a file
  pr-map does not read (`a.py` to `a.txt`) has no new side, so `a.py` is
  "removed".

- When one path gets two statuses (`R a.py b.py` with `A a.py`), "added"
  or "changed" wins over "removed": the path exists at head.

The file map labels a path with its `files` status only when it holds a
changed, added or removed box. Every other path is "unchanged", as AC-23
says of a file that only holds neighbours. That covers a file the diff
touched without touching a construct (a pure rename, an edit to imports
only), which also gets no section, so the label and the sections agree.

**Step 8, render** (AC-8, AC-10 to AC-13, AC-17, AC-19, AC-23 to AC-29).
The comment, in order:

1. **Header**, counts and legend, as today.
2. **File map** (AC-23, AC-24). One Mermaid diagram.
   - One box per path that holds a box. Its label has two lines:
     `<status>: <file name>`, then the directory (see Direction). Together
     they are the path.
   - One arrow per ordered pair of different files with at least one arrow
     between their boxes. Its label is the number of function-map arrows
     behind it; each of those is one reference site, so two calls from one
     function count twice, as the text list shows them. It is solid
     (`-->`) when any of those arrows is exact, and dashed with
     `possible, <count>` otherwise.
   - Arrows within one file are not drawn here.
3. **File sections** (AC-25 to AC-27), one per path that holds a changed,
   added or removed box, in path order. Each is
   `<details><summary>` with the path and
   `<n> changed, <n> added, <n> removed; <n> callers, <n> callees`.
   - *Anchors* are the file's changed, added and removed boxes. The
     section's boxes are the anchors and every box at the other end of an
     arrow that touches an anchor. It draws every arrow whose two ends are
     both among those boxes (AC-26: "the arrows between them"), so an arrow
     between two neighbours appears too. Callers and callees are the
     distinct boxes at the other end of arrows into and out of anchors.
   - **Collapse** (AC-27). When more than 25 of a section's boxes are in
     other files, those boxes are drawn as one box per other file:
     `<path>: <n> functions`. Their arrows are merged per file, anchor and
     direction, with the same count and solid-or-dashed rule as the file
     map. An arrow between two neighbours is merged the same way with its
     collapsed ends replaced by their file boxes; one whose two ends fall
     in the same file box is not drawn in the diagram, and stays in the
     text list. Under the diagram, the section lists each collapsed box by
     name, grouped by file. Boxes in the section's own file are never
     collapsed.
   - Splitting (AC-12) reuses `split()` on each diagram, the file map
     included, with the same budgets.

**How the file map and collapsed boxes reuse `mermaid()` and `split()`.**
Both functions take box dicts and `Edge`s. Two small changes let them draw
the new diagrams:
- `mermaid()` gains a `direction` argument (`"LR"` by default, `"TB"` for
  the file map), and draws a box's `label` field when it has one instead
  of building the label from `name`, `path` and `line`. `_label()`, which
  `split()` uses for part titles, does the same.
- `Edge` gains a `count` field, `None` by default. The file map and the
  collapse's merged arrows always set it, and it is always written:
  `-->|1|`, `-.->|possible, 3|` (AC-24). Function arrows leave it `None`
  and are drawn as today, `-->` and `-.->|possible|`.
- `comment_versions` gives the `file:` and `group:` boxes Mermaid ids the
  way it does for function boxes (`b<i>`).

A file box is then `{"id": "file:<path>", "label": ..., "status": ...}`,
and a collapsed box `{"id": "group:<path>", "label": "<path>: <n>
functions", "status": "neighbour"}`. Both live only while the comment is
written; the map's data does not change (see the rejected R2).
4. **Notes**, as today, plus the `.groundwork/` count (AC-30).
5. **Text list**, as today (AC-13): every arrow, unchanged by the
   collapse, so a collapsed box can still be searched for by name.

**Labels** (AC-29). Names and paths are written raw. Only three characters
are replaced, with the entity names Mermaid documents (C72): `<` with
`#lt;`, `>` with `#gt;`, and `"` with `#quot;`. Lines stay separated by a
newline. This replaces `MERMAID_ESCAPES`.
- From mermaid 11.14 this shows every tested name exactly with HTML labels,
  and every name but one with SVG text labels (C69). The exception is a
  `"`, which Python and TypeScript names cannot hold.
- A raw `<` is not an option: `Map<string, T>` would show as `Map` (C71).
- The underscore needs no escape, because plain labels stopped being
  read as markdown in 11.13 (C67, C68).
- **Gaps.** Which mermaid version github.com runs is unverified (C74).
  On 11.12 or earlier, `__init__` would show as a bold "init", and no
  encoding is exact in both label modes (C67). A path holding `#` followed
  by a word and `;` would read as an entity code. Step 0 above checks the
  version on GitHub.

**Theme** (AC-28). No diagram sets a fill or a text colour. Status is shown
by the label text, as now, and by the outline:

| Status | Outline |
|---|---|
| changed | `stroke:#9a6700,stroke-width:3px` (solid) |
| added | `stroke:#1a7f37,stroke-width:3px,stroke-dasharray:8 4` |
| removed | `stroke:#cf222e,stroke-width:3px,stroke-dasharray:2 4` |
| neighbour, unchanged file | none: the theme's 1-pixel outline |

- With no fill set, text contrast is at least 10:1 in the default,
  neutral and dark themes (C75).
- The three strokes reach at least 3:1 against both GitHub backgrounds and
  every theme's node fill (C76), the contrast WCAG asks of graphics.
- Width and dash tell the statuses apart without colour (C77). The dash
  numbers are written with a space, because a comma separates properties
  in a `classDef`.
- File map boxes use the same classes by file status.

**Direction.** The file map is `flowchart TB`, with each box's file
name on the first line and its directory on the second. On a 358-pixel
phone column, six files then take 405 pixels instead of 1,113 left to
right (C81). Function diagrams stay `flowchart LR`, which is narrower than
top to bottom for them (907 against 3,085 pixels for 25 boxes, C81).
- The SVG shrinks to fit the column rather than scrolling (C82), so a wide
  diagram gets small text instead of being cut off. Text stays 12 pixels or
  larger only up to about 477 pixels wide (C81); a section near the AC-27
  limit of 25 will need zooming. The limit is a constant, set to 25 as
  approved.
- GitHub Mobile does not render Mermaid at all (C80). There the section
  titles, the notes and the text list carry the map on their own.

**Shrinking for 422** (AC-14), in order: the text list moves out; then
file sections, last first, one per version; then the file map; last, the
header, counts and link. Each version says what moved.

### Tests (revision 2)

The acceptance tests change with the criteria. That stage lists every
changed assertion and why. The unit tests change with the code: the
`escape` assertions in `unit_render.py` follow the new label rule.
Expected changes to the acceptance tests in `test_render.py`:

- Tests that count diagrams (`len(parts) == 1`) count the diagrams in one
  section instead, because the comment now holds a file map too.
- The text-list test finds the text list by its summary, because file
  sections are `<details>` too.
- The 600-caller test stays (every box and arrow is still drawn), but
  looks for collapsed callers in the section's list and the text list.

New tests, one or more per new criterion: the file map's boxes, counts and
arrow styles (AC-23, AC-24); section order, titles and contents (AC-25,
AC-26); the collapse at 26 and not at 25 (AC-27); no `fill` or `color` in
any diagram (AC-28); labels that keep `merge_base` and `__init__` raw, write `Map<string, T>` as `Map#lt;string, T#gt;`, and contain no decimal entity code (AC-29); a fixture with a
`.groundwork/` file changed and called (AC-30); and a rename that deletes a
function, whose old path is a "removed" file, and a pure rename whose file
holds a neighbour, labelled "unchanged" (AC-23); and a file arrow backed by
one function arrow, labelled `1` (AC-24).

### Criteria coverage (revision 2)

| Criterion | How the design meets it |
|---|---|
| AC-11 | Every box and arrow is in the section of each changed file it touches, and in the text list; the collapse lists collapsed boxes by name |
| AC-12 | `split()` on the file map and on each section's diagram |
| AC-23 | File map: one box per path, labelled with path and status from `files` |
| AC-24 | File arrows counted over the function map; solid if any is exact |
| AC-25 | One `<details>` per file with an anchor, path order, counts in the summary |
| AC-26 | Section draws the arrows touching its anchors and their ends |
| AC-27 | Collapse when more than 25 boxes are in other files; names listed under the diagram |
| AC-28 | No `fill` or `color` in any diagram; status in the label text and the outline (C75 to C77) |
| AC-29 | Raw names except `<`, `>` and `"` (C69, C71); the version on GitHub checked in step 0 (C74) |
| AC-30 | `.groundwork/` prefix skipped in steps 1 and 2; count in the notes |

### Project rules check (revision 2)

1. **Reuse:** `split()`, `mermaid()`, `_text_list()` and `_notes()` are
   reused; the file map is drawn by the same `mermaid()`.
2. **Simplest design:** no new module or option. The collapse threshold
   is a constant, as the budgets are.
4. **One representation:** file arrows are computed when drawing, not
   stored (see the rejected R2).
5. **Tests from criteria:** the render tests use hand-built maps, as
   today; AC-30 uses a fixture repository.
6. **Never weaken a check:** changed assertions are listed in the
   acceptance-test stage with the criterion that changed them.
8. **Sources:** the label, colour and size choices rest on measurements in
   `spike/mermaid/` (C65 to C78, C81, C82). Three facts are unverified:
   github.com's mermaid version (C74), collapsed sections on GitHub (C79,
   Tier 2), and GitHub Mobile (C80, Tier 2). Step 0 checks the first two
   on GitHub itself before the build.
