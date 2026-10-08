"""Answer "where is this defined?" at a reference site, and turn each answer into an arrow or none.

Design: docs/specs/pr-map/design.md, Pipeline step 6 (verdicts) and step 7
(resolvers). `Resolver.definition_at` is the one source of answers; the
verdict functions below are pure, so graph assembly can feed them
candidates and answers from any language.

Python answers come from jedi in this process: `Script.goto` with
`follow_imports` (research.md C41) and `Script.get_references` (C17b).
TypeScript answers come from the Node helper resolve_ts.cjs, which runs the
pinned TypeScript LanguageService (C36, C13) and talks one JSON object per
line over standard input and output. When Node or the helper is missing, or
the helper dies or stops answering, every TypeScript request raises
ResolverError with that reason, which the verdicts read as "resolver failed".
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import constructs
import jedi
from constructs import Construct, FileConstructs
from groundwork_config import SKIP_DIRS, walk_files
from tree_sitter import Node

# jedi infers an untyped parameter's type from the calls it sees (C58, C59). It
# then answered one class's method for `obj.save()` although two classes are
# passed in; with both off it answers nothing (C60), which becomes a possible
# arrow (AC-6) instead of a wrong solid one.
jedi.settings.dynamic_params = False
jedi.settings.dynamic_params_for_other_modules = False

PROJECT_MARKERS = ("pyproject.toml", "setup.cfg", "setup.py")
CONSTRUCTORS = {"__init__", "__new__"}

TYPESCRIPT = (".ts", ".tsx")
HELPER = Path(__file__).resolve().parent / "resolve_ts.cjs"
# Seconds the helper may take over one answer. The first request in a project
# builds its program, which takes seconds on a large repository; a helper that
# takes longer is stopped and treated as failed (design, workflow "Hangs").
HELPER_TIMEOUT = 120.0

log = logging.getLogger("pr_map")

CALLER, CALLEE, REMOVED = "caller", "callee", "removed"

# Python node types that open a scope for name lookup. A class body is not one
# for the code inside its methods, so it is left out.
COMPREHENSIONS = ("list_comprehension", "set_comprehension", "dictionary_comprehension", "generator_expression")
SCOPES = ("function_definition", "lambda", "module", *COMPREHENSIONS)


class ResolverError(RuntimeError):
    """The resolver could not answer at a site; the message names the site and the resolver's reason."""


@dataclass(frozen=True)
class Location:
    """One place an answer points at."""

    path: str | None  # relative to the repository root; None outside it (a library, the standard library)
    line: int  # 1-based
    column: int  # 0-based character column
    kind: str  # jedi's Name.type ("function", "class", "param", ...) or TypeScript's DefinitionInfo.kind
    name: str  # dotted full name where the resolver knows it, else the bare name
    local: bool = False  # a parameter, or a variable assigned inside a function


@dataclass(frozen=True)
class Candidate:
    """A reference site that may refer to a box (design, Pipeline step 5)."""

    path: str
    line: int  # 1-based
    column: int  # 0-based character column
    name: str  # the identifier's text
    call: bool  # the identifier is the function of a call
    role: str  # CALLER or REMOVED (of target), or CALLEE (of the box around the site)
    target: str | None = None  # box id; None for a callee
    through: str = ""  # a runtime class (`cls`, `type(self)`) that may run target: always possible
    referenced: bool = False  # TypeScript: the site came from the target's own findReferences (C43 to C45, C54)


@dataclass(frozen=True)
class Answer:
    """What the resolver said at a candidate's site."""

    locations: tuple[Location, ...] = ()
    error: str = ""  # the resolver failed, and why
    traced: str = ""  # where the name's import leads (trace_import): "library", "repository" or ""


@dataclass(frozen=True)
class Verdict:
    """The arrow a candidate becomes, or why there is none.

    certainty "" means no arrow. note says what the text section lists
    instead: "library" (a library call, counted), "refers" (a repository
    definition that is not a box, at refers_to), "unresolved" (a callee with
    several possible targets, in options) or "removed constructor" (a call of
    a class whose constructor target was removed).
    """

    certainty: str  # "exact" | "possible" | ""
    target: str = ""
    reason: str = ""
    note: str = ""
    refers_to: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Code:
    """What the verdicts know about the repository's constructs."""

    constructs: Mapping[str, Construct]  # every construct in the head commit, and removed ones, by id
    positions: Mapping[tuple[str, int, int], str]  # every head name position -> construct id
    bases: Mapping[str, tuple[str, ...]]  # Python class id -> its bases: class ids, or names outside the repository
    # TypeScript method id -> the interface members it may be called through by shape (Resolver.structural)
    implements: Mapping[str, frozenset[str]] = field(default_factory=dict)


def index(files: Iterable[FileConstructs]) -> tuple[dict[str, Construct], dict[tuple[str, int, int], str]]:
    """Constructs by id and by name position. An overload group has one position per signature."""
    by_id: dict[str, Construct] = {}
    positions: dict[tuple[str, int, int], str] = {}
    for file in files:
        for c in file.constructs:
            by_id[c.id] = c
            for line, column in c.names:
                positions[(c.path, line, column)] = c.id
    return by_id, positions


class TypeScript:
    """The Node helper resolve_ts.cjs, started on first use and asked one request at a time.

    This is pr-map's one fallback (design, step 7): when Node or the helper
    is missing, or the helper dies or does not answer within HELPER_TIMEOUT,
    a warning is logged once, failure records why, and this request and
    every later one raise ResolverError with that reason. The verdicts turn
    those into possible arrows, "resolver failed: ...".
    """

    def __init__(
        self,
        root: Path,
        packages: Sequence[str],
        node: str = "node",
        helper: Path = HELPER,
        timeout: float = HELPER_TIMEOUT,
    ):
        self.root = root
        self.packages = list(packages)  # workspace package directories, relative to root
        self.node = node
        self.helper = helper
        self.timeout = timeout
        self.failure = ""
        self._process: subprocess.Popen | None = None
        self._answers: queue.Queue[str | None] = queue.Queue()
        self._stderr: deque[str | None] = deque(maxlen=100)
        self._threads: list[threading.Thread] = []
        self._next_id = 0

    def ask(self, request: dict) -> dict:
        """Send one request and return its answer; raises ResolverError when the helper fails or answers an error."""
        if self.failure:
            raise ResolverError(f"TypeScript resolver unavailable: {self.failure}")
        if self._process is None:
            self._start()
        self._next_id += 1
        line = json.dumps({"id": self._next_id, **request}) + "\n"
        try:
            self._process.stdin.write(line)
            self._process.stdin.flush()
        except OSError as exc:
            raise self._fail(f"the helper stopped reading requests ({exc})") from exc
        try:
            text = self._answers.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise self._fail(f"the helper gave no answer within {self.timeout:g} s") from exc
        if text is None:
            self._process.wait()
            raise self._fail(f"the helper exited with code {self._process.returncode}{self._last_stderr()}")
        try:
            answer = json.loads(text)
        except json.JSONDecodeError as exc:
            raise self._fail(f"the helper wrote something that is not JSON: {text[:200]!r}") from exc
        if answer.get("id") != self._next_id:
            raise self._fail(f"the helper answered request {answer.get('id')} instead of {self._next_id}")
        if "error" in answer:
            raise ResolverError(f"TypeScript {request['op']}: {answer['error']}")
        return answer

    def close(self) -> None:
        """Ask the helper to exit by closing its input, stop it if it does not, and close the pipes."""
        if self._process is None:
            return
        if self._process.poll() is None:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._process.kill()
                self._process.wait()
        for thread in self._threads:
            thread.join(timeout=5)
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            try:
                stream.close()
            except BrokenPipeError:
                pass  # unsent input to a helper that already exited: nothing is waiting for it

    def _start(self) -> None:
        if not self.helper.is_file():
            raise self._fail(f"the helper {self.helper} is missing")
        command = [self.node, str(self.helper), str(self.root), json.dumps(self.packages)]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            raise self._fail(f"Node could not be started as {self.node!r} ({exc})") from exc
        self._threads = [
            threading.Thread(target=self._read, args=(self._process.stdout, self._answers.put), daemon=True),
            threading.Thread(target=self._read, args=(self._process.stderr, self._stderr.append), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    @staticmethod
    def _read(stream, put) -> None:
        """Pass each line of stream to put, then None at its end (stdout's end means the helper exited)."""
        for line in stream:
            put(line.rstrip("\n"))
        put(None)

    def _last_stderr(self) -> str:
        """Node's error line from the helper's standard error ("Error: Cannot find module 'typescript'")."""
        for thread in self._threads[1:]:
            thread.join(timeout=5)
        lines = [line for line in self._stderr if line]
        errors = [line for line in lines if "Error" in line.split(":")[0]]
        return f": {(errors or lines)[0 if errors else -1]}" if lines else ""

    def _fail(self, reason: str) -> ResolverError:
        self.failure = reason
        log.warning("TypeScript references fall back to possible arrows: %s", reason)
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self.close()
        return ResolverError(f"TypeScript resolver unavailable: {reason}")


class Resolver:
    """definition_at and reference search for the files of one repository, read from its working tree."""

    def __init__(self, root: Path, node: str = "node"):
        self.root = root.resolve()
        self.node = node  # the Node executable for the TypeScript helper
        self._projects: dict[Path, jedi.Project] = {}
        self._scripts: dict[str, jedi.Script] = {}
        self._modules: frozenset[str] | None = None
        self._typescript: TypeScript | None = None
        self._lines: dict[str, list[str]] = {}

    @property
    def typescript_failure(self) -> str:
        """Why TypeScript answers fell back to possible arrows, for the comment's notes; "" when they did not."""
        return self._typescript.failure if self._typescript is not None else ""

    def close(self) -> None:
        """Stop the TypeScript helper, if it was started."""
        if self._typescript is not None:
            self._typescript.close()

    def definition_at(self, path: str, line: int, column: int) -> list[Location]:
        """Where the identifier at path:line:column (1-based line, character column) is defined."""
        if Path(path).suffix in TYPESCRIPT:
            return self._ask_locations("definition", path, line, column)
        script = self._script(path, line, column)
        try:
            names = script.goto(line, column, follow_imports=True)
        except (ValueError, jedi.InternalError) as exc:
            raise ResolverError(f"jedi goto at {path}:{line}:{column}: {exc}") from exc
        return [self._location(name) for name in names]

    def references(self, path: str, line: int, column: int) -> list[Location]:
        """Every place jedi finds that refers to the definition named at path:line:column, without itself.

        Import lines are included. jedi finds the name in a renaming import
        but not the calls through it (C46), and may stop early (C24).
        TypeScript's findReferences follows renames, interfaces and
        constructors (C43 to C45, C53, C62); its definition entries are left
        out.
        """
        if Path(path).suffix in TYPESCRIPT:
            found = self._ask_locations("references", path, line, column)
            return [loc for loc in found if (loc.path, loc.line, loc.column) != (path, line, column)]
        script = self._script(path, line, column)
        try:
            names = script.get_references(line, column, scope="project")
        except (ValueError, jedi.InternalError) as exc:
            raise ResolverError(f"jedi references at {path}:{line}:{column}: {exc}") from exc
        found = [self._location(name) for name in names]
        return [loc for loc in found if (loc.path, loc.line, loc.column) != (path, line, column)]

    def class_bases(self, cls: Construct, positions: Mapping[tuple[str, int, int], str]) -> tuple[str, ...]:
        """A Python class's bases: the class box each resolves to, else its full name (`typing.Protocol`).

        A base the resolver cannot place keeps the name the source gives it,
        so it still counts as a class outside the repository. Raises
        ResolverError when jedi fails on a base.
        """
        source = self._source(cls.path).splitlines()
        bases = []
        for line, column in cls.bases:
            text = source[line - 1]
            end = column
            while end < len(text) and (text[end].isalnum() or text[end] == "_"):
                end += 1
            found = self.definition_at(cls.path, line, column)
            boxes = [positions[key] for key in ((loc.path, loc.line, loc.column) for loc in found) if key in positions]
            if boxes:
                bases.append(boxes[0])
            elif found:
                bases.append(found[0].name)
            else:
                bases.append(text[column:end])
        return tuple(bases)

    def trace_import(self, path: str, line: int, column: int) -> str:
        """Where the name at a site comes from: "library", "repository" or "" (design, step 6).

        The leftmost name of an attribute chain (`np` in `np.mean`) is looked
        up in its scope. An import of a module not found in the repository is
        "library"; one that is found, or a relative import, is "repository"
        (see _in_repository).
        A variable assigned once in that scope is traced through its value's
        leftmost name, and a parameter through its type annotation, one step
        only. Anything else, such as an untyped parameter or a variable
        assigned twice, is "".

        TypeScript is traced by the helper with the type checker, the same
        way: an import whose bare specifier is neither a workspace package
        nor a `paths` key of the file's project is "library".
        """
        if Path(path).suffix in TYPESCRIPT:
            request = {"op": "trace", **self._where(path, line, column)}
            return self._helper().ask(request)["traced"]
        if Path(path).suffix != ".py":
            raise ResolverError(f"tracing imports in {path}: no resolver for {Path(path).suffix} files")
        source = self._source(path).encode("utf-8")
        tree = constructs.syntax(path, source)
        lines = source.split(b"\n")
        byte_column = len(lines[line - 1].decode("utf-8")[:column].encode("utf-8"))
        node = tree.root_node.named_descendant_for_point_range((line - 1, byte_column), (line - 1, byte_column))
        module = _trace(node, follow=True) if node is not None else None
        if module is None:
            return ""
        if module.startswith(".") or self._in_repository(module.split(".")[0]):
            return "repository"
        return "library"

    def structural(self, target: Construct, constructs: Iterable[Construct]) -> frozenset[str]:
        """Interface members a TypeScript method may be called through by shape (design, step 6).

        A member with the method's name, in an interface its class is
        assignable to by the type checker (C63, C64), whether or not the class
        says `implements`. The helper also requires the member to be a
        function: a method signature, or a property whose type has call
        signatures. Raises ResolverError when the helper fails.
        """
        found: set[str] = set()
        by_id = {c.id: c for c in constructs}
        cls = by_id.get(target.parent or "")
        if Path(target.path).suffix not in TYPESCRIPT or target.kind != "method" or cls is None:
            return frozenset()
        for c in by_id.values():
            holder = by_id.get(c.parent or "")
            if c.kind != "member" or _short(c) != _short(target) or holder is None or holder.id == cls.id:
                continue
            if holder.kind != "class" or Path(c.path).suffix not in TYPESCRIPT:
                continue
            request = {
                "op": "assignable",
                "source": self._where(cls.path, cls.line, cls.column),
                "target": self._where(c.path, c.line, c.column),
            }
            if self._helper().ask(request)["assignable"]:
                found.add(c.id)
        return frozenset(found)

    def _helper(self) -> TypeScript:
        if self._typescript is None:
            packages = [
                file.parent.relative_to(self.root).as_posix()
                for file in walk_files(self.root)
                if file.name == "package.json"
            ]
            self._typescript = TypeScript(self.root, packages, self.node)
        return self._typescript

    def _where(self, path: str, line: int, column: int) -> dict:
        """A site as the helper takes it: the column in UTF-16 code units, TypeScript's unit."""
        text = self._line(path, line)
        return {"file": path, "line": line, "column": len(text[:column].encode("utf-16-le")) // 2}

    def _ask_locations(self, op: str, path: str, line: int, column: int) -> list[Location]:
        answer = self._helper().ask({"op": op, **self._where(path, line, column)})
        return [self._ts_location(found) for found in answer["locations"]]

    def _ts_location(self, found: dict) -> Location:
        """A helper location as a Location: column back in characters; outside the repository, or in a
        skipped directory (an installed package, the compiler's own lib files), path is None."""
        file = Path(found["file"])
        path = None
        if file.is_relative_to(self.root):
            rel = file.relative_to(self.root)
            if not SKIP_DIRS.intersection(rel.parts[:-1]):
                path = rel.as_posix()
        column = found["column"]
        if path is not None:
            units = self._line(path, found["line"]).encode("utf-16-le")[: 2 * column]
            column = len(units.decode("utf-16-le"))
        return Location(path, found["line"], column, found["kind"], found["name"], found["local"])

    def _line(self, path: str, line: int) -> str:
        if path not in self._lines:
            self._lines[path] = self._source(path).split("\n")
        lines = self._lines[path]
        if not 1 <= line <= len(lines):
            raise ResolverError(f"reading {path}:{line} for the resolver: the file has {len(lines)} lines")
        return lines[line - 1]

    def _in_repository(self, top: str) -> bool:
        """A top-level module is in the repository when a `<top>.py` file or a `<top>` directory holding
        Python files exists anywhere in it, outside the skip list. Code can reach any of them through
        `sys.path`, so this is wider than the project roots on purpose: a repository module read as a
        library would drop its callers."""
        if self._modules is None:
            modules: set[str] = set()
            for file in walk_files(self.root):
                if file.suffix == ".py":
                    modules.add(file.stem)
                    modules.update(file.relative_to(self.root).parts[:-1])
            self._modules = frozenset(modules)
        return top in self._modules

    def _project(self, path: str) -> jedi.Project:
        """One jedi Project per nearest directory with a project file, else the repository root."""
        directory = (self.root / path).parent
        while directory != self.root and not any((directory / m).is_file() for m in PROJECT_MARKERS):
            directory = directory.parent
        if directory not in self._projects:
            self._projects[directory] = jedi.Project(directory)
        return self._projects[directory]

    def _source(self, path: str) -> str:
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ResolverError(f"reading {path} for the resolver: {exc}") from exc

    def _script(self, path: str, line: int, column: int) -> jedi.Script:
        if Path(path).suffix != ".py":
            raise ResolverError(f"resolving {path}:{line}:{column}: no resolver for {Path(path).suffix} files")
        if path not in self._scripts:
            self._scripts[path] = jedi.Script(self._source(path), path=self.root / path, project=self._project(path))
        return self._scripts[path]

    def _location(self, name) -> Location:
        """A jedi Name as a Location; outside the repository, or in a skipped directory, path is None."""
        path = None
        if name.module_path is not None:
            module = Path(name.module_path).resolve()
            if module.is_relative_to(self.root):
                rel = module.relative_to(self.root)
                if not SKIP_DIRS.intersection(rel.parts[:-1]):
                    path = rel.as_posix()
        local = False
        if path is not None:
            parent = name.parent()
            local = name.type == "param" or (
                name.type == "statement"
                and parent is not None
                and parent.type == "function"
                and not name.get_line_code()[: name.column].endswith(".")  # `self.x = ...` is an attribute
            )
        return Location(
            path=path,
            line=name.line or 0,
            column=name.column or 0,
            kind=name.type,
            name=name.full_name or name.name,
            local=local,
        )


def mro(cls: str, bases: Mapping[str, tuple[str, ...]]) -> list[str]:
    """Python's C3 linearization of cls. A name that is not a key of bases is a class with no known bases.

    Raises ValueError when the bases cannot be ordered, as Python itself
    does (TypeError at class creation), or when they form a cycle.
    """

    def linearize(name: str, seen: tuple[str, ...]) -> list[str]:
        if name in seen:
            raise ValueError(f"the bases of {name} form a cycle")
        parents = bases.get(name, ())
        sequences = [linearize(p, (*seen, name)) for p in parents] + [list(parents)]
        order = [name]
        while any(sequences):
            for sequence in sequences:
                head = sequence[0] if sequence else None
                if head is not None and not any(head in s[1:] for s in sequences):
                    break
            else:
                raise ValueError(f"cannot order the bases of {name} (no consistent method resolution order)")
            order.append(head)
            sequences = [s[1:] if s and s[0] == head else s for s in sequences]
        return order

    return linearize(cls, ())


def runners(cls: str, method: str, code: Code) -> dict[str, str]:
    """Classes whose instances run cls.method when constructed: each maps to "" when certain, or to the
    first class before cls in its order that might define the method itself: one outside the repository,
    or a decorated one (`@dataclass` generates `__init__`).

    A class is a runner when its order reaches cls before any other repository
    class that defines method (design, step 5: a mixin listed first, or a
    subclass with its own `__init__`, takes it out).
    """
    found = {other: _runs(other, cls, method, code) for other in code.bases.keys() | {cls}}
    return {other: outside for other, outside in found.items() if outside is not None}


def _runs(other: str, cls: str, method: str, code: Code) -> str | None:
    """Whether constructing other runs cls.method: None when not, else as in runners."""
    order = mro(other, code.bases)
    if cls not in order:
        return None
    live = set(code.positions.values())
    defines = {c.parent for c in code.constructs.values() if c.id in live and c.parent and _short(c) == method}
    outside = ""
    for name in order[: order.index(cls)]:
        if name in defines:
            return None
        if name not in code.bases and name != "builtins.object" and not outside:
            outside = name
        decorated = name in code.constructs and code.constructs[name].start_line < code.constructs[name].line
        if decorated and not outside:
            outside = name  # a class decorator such as @dataclass may generate the method
    return outside


def ancestors(cls: str, bases: Mapping[str, tuple[str, ...]]) -> set[str]:
    """Every class cls inherits from, directly or further up; a cycle stops instead of looping."""
    found: set[str] = set()
    pending = list(bases.get(cls, ()))
    while pending:
        name = pending.pop()
        if name not in found and name != cls:
            found.add(name)
            pending.extend(bases.get(name, ()))
    return found


def related(target: str, code: Code) -> set[str]:
    """Boxes related to a Python method target (design, step 6, "Related box").

    A member with the target's name in a class the target's class inherits
    from, directly or further up, or in a `Protocol` class.
    """
    t = code.constructs[target]
    if t.parent is None or code.constructs[t.parent].kind != "class":
        return set()
    name = _short(t)
    protocols = {c for c, bs in code.bases.items() if any(b.rsplit(".", 1)[-1] == "Protocol" for b in bs)}
    classes = (ancestors(t.parent, code.bases) | protocols) - {t.parent}
    live = set(code.positions.values())
    return {c.id for c in code.constructs.values() if c.parent in classes and _short(c) == name and c.id in live}


def verdict(candidate: Candidate, answer: Answer, code: Code, named: Sequence[str] = ()) -> Verdict:
    """The verdict table of design step 6 for one candidate and its answer.

    named lists the box ids whose match key equals the candidate's name; a
    callee that does not resolve gets a possible arrow only when there is
    exactly one.
    """
    if candidate.through:
        return Verdict("possible", candidate.target or "", f"through `{candidate.through}`")
    if answer.error:
        return _unresolved(candidate, named, f"resolver failed: {answer.error}")

    locations = answer.locations
    if Path(candidate.path).suffix in TYPESCRIPT:
        # Without the library installed, TypeScript answers a library name with its own import line (C57),
        # and an import of a missing repository module the same way: that says nothing yet (design, step 6).
        locations = tuple(loc for loc in locations if loc.kind != "alias")
        locations, note = _read_construction(locations, candidate, code)
        if note:
            return Verdict("", target=candidate.target or "", note=note)

    boxes: list[str] = []
    uncertain = ""
    local = refers = False
    refers_to = ""
    for loc in locations:
        box = code.positions.get((loc.path, loc.line, loc.column)) if loc.path is not None else None
        if box is not None:
            box, how = _read_class_answer(box, candidate, code)
            if how == "removed constructor":
                return Verdict("", note="removed constructor", target=candidate.target or "")
            if how.startswith("resolver failed"):
                return _unresolved(candidate, named, how)
            uncertain = uncertain or how
            if box not in boxes:
                boxes.append(box)
        elif loc.path is None:
            continue
        elif loc.local:
            local = True
        elif not refers:
            refers, refers_to = True, f"{loc.path}:{loc.line}"

    if candidate.role == CALLER and boxes == [candidate.target]:
        if uncertain:
            return Verdict("possible", candidate.target, f"through `{uncertain}`")
        return Verdict("exact", candidate.target)
    if candidate.role == CALLER and candidate.target not in boxes:
        through = sorted(_related(candidate, code).intersection(boxes)) if candidate.target else []
        if through:
            return Verdict("possible", candidate.target, f"through `{through[0]}`")
    if boxes:
        if len(boxes) == 1:
            return Verdict("exact", boxes[0]) if candidate.role == CALLEE else Verdict("")
        return _unresolved(candidate, named, "unresolved")
    if local:
        return Verdict("")
    if refers:
        return Verdict("", note="refers", refers_to=refers_to) if candidate.role != REMOVED else Verdict("")
    if locations:
        return Verdict("")  # a definition outside the repository
    if answer.traced == "library":
        return Verdict("", note="library")
    return _unresolved(candidate, named, "unresolved import" if answer.traced == "repository" else "unresolved")


def _related(candidate: Candidate, code: Code) -> set[str]:
    """Boxes a caller may reach the candidate's target through (design, step 6, "Related box").

    TypeScript: any box the site resolves to when the site came from the
    target's own findReferences, which links them through renames,
    interfaces, base classes and typed object literals (C43 to C45, C54);
    and the interface members the target's class matches by shape
    (Code.implements). Python: see related.
    """
    target = code.constructs[candidate.target or ""]
    if Path(target.path).suffix not in TYPESCRIPT:
        return related(target.id, code)
    linked = set(code.implements.get(target.id, ()))
    if candidate.referenced:
        linked.update(code.positions.values())
    return linked


def _read_construction(
    locations: tuple[Location, ...], candidate: Candidate, code: Code
) -> tuple[tuple[Location, ...], str]:
    """Read a TypeScript construction against the candidate's target (design, step 6).

    `new Foo(1)`, `super(...)` and `new this(...)` answer with the class and
    the constructor that runs (C52, C61); `new Plain(3)` for a subclass
    without its own constructor answers Plain and its base's constructor.
    The pair counts as the class when the class is the target, else as the
    constructor; for a callee, as the class when it inherits the
    constructor. A type annotation or `Foo.make()` answers the class alone,
    which stays the class. A call of the class whose removed constructor is
    the target returns the note "removed constructor".
    """
    box_at = {loc: code.positions.get((loc.path, loc.line, loc.column)) for loc in locations}
    classes = {b for b in box_at.values() if b is not None and code.constructs[b].kind == "class"}
    target = code.constructs.get(candidate.target or "")
    if (
        candidate.role == REMOVED
        and candidate.call
        and target is not None
        and _short(target) == "constructor"
        and target.parent in classes
    ):
        return locations, "removed constructor"
    runs = [loc for loc in locations if loc.kind == "constructor" and box_at[loc] is not None]
    if not runs:
        return locations, ""
    inherited = {b for b in classes if not any(code.constructs[box_at[r]].parent == b for r in runs)}
    if candidate.role != CALLEE and candidate.target in classes:
        chosen = {loc for loc in locations if box_at[loc] == candidate.target}
    elif candidate.role == CALLEE and inherited:
        # A callee `new Plain()` is one arrow to the constructor when the class defines one, else to the class.
        chosen = {loc for loc in locations if box_at[loc] in inherited}
    else:
        chosen = set(runs)
    pair = set(runs) | {loc for loc in locations if box_at[loc] in classes}
    return tuple(loc for loc in locations if loc in chosen or loc not in pair), ""


def _read_class_answer(box: str, candidate: Candidate, code: Code) -> tuple[str, str]:
    """Read a class answer against the candidate's target (design, step 6, "A class with its constructor").

    Returns the box the answer counts as and, when that box is reached
    through a class that might run its own constructor first, that class's
    name; or a note: "removed constructor", or "resolver failed: ...".
    """
    c = code.constructs[box]
    if c.kind != "class" or Path(c.path).suffix != ".py":
        return box, ""  # TypeScript constructions are read by _read_construction
    if candidate.role == CALLEE:
        if candidate.call:
            live = set(code.positions.values())
            own = {_short(k): k.id for k in code.constructs.values() if k.parent == box and k.id in live}
            return next((own[m] for m in ("__init__", "__new__") if m in own), box), ""
        return box, ""
    target = code.constructs.get(candidate.target or "")
    if target is None or _short(target) not in CONSTRUCTORS or not candidate.call:
        return box, ""
    try:
        outside = _runs(box, target.parent or "", _short(target), code)
    except ValueError as exc:
        return box, f"resolver failed: {exc}"
    if outside is None:
        return box, ""
    if candidate.role == REMOVED:
        return box, "removed constructor"
    return target.id, outside


def _short(c: Construct) -> str:
    """The last segment of a construct's name: its match key, except for constructors (design, step 5)."""
    return c.name.rsplit(".", 1)[-1]


def _unresolved(candidate: Candidate, named: Sequence[str], reason: str) -> Verdict:
    """A possible arrow to the candidate's target; for a callee, only when exactly one box has its name."""
    if candidate.role == REMOVED and reason in ("unresolved", "unresolved import"):
        return Verdict("possible", candidate.target or "", "unresolved")
    if candidate.role != CALLEE:
        return Verdict("possible", candidate.target or "", reason)
    if len(named) == 1:
        return Verdict("possible", named[0], reason)
    return Verdict("", note="unresolved", reason=reason, options=tuple(named))


def _trace(node: Node, follow: bool) -> str | None:
    """The module the leftmost name at node was imported from, or None (see Resolver.trace_import)."""
    name = _leftmost(node)
    if name is None:
        return None
    scope = name.parent
    while scope is not None and scope.type not in SCOPES:
        scope = scope.parent
    while scope is not None:
        bindings = _bindings(scope, name.text.decode("utf-8"))
        if bindings:
            if len(bindings) != 1:
                return None
            kind, value = bindings[0]
            if kind == "import":
                return value
            if kind in ("assign", "annotation") and follow:
                return _trace(value, follow=False)
            return None
        scope = scope.parent
        while scope is not None and scope.type not in SCOPES:
            scope = scope.parent
    return None


def _leftmost(node: Node) -> Node | None:
    """The first name of an expression: `np` in `np.mean`, `np.array(xs).mean` or `Command[int]`."""
    if node.type == "identifier" and node.parent is not None and node.parent.type == "attribute":
        if node.parent.child_by_field_name("attribute") == node:
            node = node.parent
    if node.type == "type" and node.named_children:
        node = node.named_children[0]  # a parameter's annotation
    while node.type in ("attribute", "call", "subscript"):
        field = {"attribute": "object", "call": "function", "subscript": "value"}[node.type]
        node = node.child_by_field_name(field)
    return node if node.type == "identifier" else None


def _bindings(scope: Node, name: str) -> list[tuple[str, object]]:
    """How name is bound directly in scope: ("import", module), ("assign", value node),
    ("annotation", type node) for a typed parameter, or ("other", None)."""
    found: list[tuple[str, object]] = []
    if scope.type in COMPREHENSIONS:
        for clause in scope.named_children:
            target = clause.child_by_field_name("left") if clause.type == "for_in_clause" else None
            if target is not None and any(
                n.type == "identifier" and n.text.decode("utf-8") == name for n in _descendants(target)
            ):
                found.append(("other", None))
        return found
    if scope.type in ("function_definition", "lambda"):
        parameters = scope.child_by_field_name("parameters")
        for p in parameters.named_children if parameters is not None else ():
            if p.type in ("list_splat_pattern", "dictionary_splat_pattern") and p.named_children:
                p = p.named_children[0]  # `*args`, `**kw`
            if p.type == "identifier" and p.text.decode("utf-8") == name:
                found.append(("other", None))
            elif p.type in ("typed_parameter", "typed_default_parameter"):
                inner = p.child_by_field_name("name") or p.named_children[0]
                splat = inner.type in ("list_splat_pattern", "dictionary_splat_pattern")
                if splat and inner.named_children:
                    inner = inner.named_children[0]  # `*args: T` holds a tuple of T, not a T
                if inner.type == "identifier" and inner.text.decode("utf-8") == name:
                    found.append(("other", None) if splat else ("annotation", p.child_by_field_name("type")))
            elif p.type == "default_parameter" and p.child_by_field_name("name").text.decode("utf-8") == name:
                found.append(("other", None))
        body = scope.child_by_field_name("body")
        pending = list(body.named_children) if body is not None and scope.type != "lambda" else []
    else:
        pending = list(scope.named_children)
    while pending:
        node = pending.pop()
        if node.type in ("function_definition", "class_definition"):
            if node.child_by_field_name("name").text.decode("utf-8") == name:
                found.append(("other", None))
            continue
        if node.type == "lambda":
            continue
        if node.type == "import_statement":
            for item in node.named_children:
                found += _import_binding(item, name, None)
        elif node.type == "import_from_statement":
            module = node.child_by_field_name("module_name").text.decode("utf-8")
            for item in node.children_by_field_name("name"):
                found += _import_binding(item, name, module)
        elif node.type in ("assignment", "augmented_assignment"):
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier" and left.text.decode("utf-8") == name:
                value = node.child_by_field_name("right")
                plain = node.type == "assignment" and value is not None and value.type != "assignment"
                found.append(("assign", value) if plain else ("other", None))
            elif left is not None and any(
                n.type == "identifier" and n.text.decode("utf-8") == name for n in _descendants(left)
            ):
                found.append(("other", None))  # unpacking: `a, b = ...`
            pending.extend(n for n in node.named_children if n != left)
        elif node.type in ("for_statement", "as_pattern", "named_expression"):
            field = {"for_statement": "left", "as_pattern": "alias", "named_expression": "name"}[node.type]
            target = node.child_by_field_name(field)
            if target is not None and any(
                n.type == "identifier" and n.text.decode("utf-8") == name for n in _descendants(target)
            ):
                found.append(("other", None))  # a loop variable, `with ... as`, `except ... as` or `:=`
            pending.extend(node.named_children)
        else:
            pending.extend(node.named_children)
    return found


def _import_binding(item: Node, name: str, module: str | None) -> list[tuple[str, object]]:
    """The binding one imported item makes, if it binds name: `import a.b` binds `a`."""
    if item.type == "aliased_import":
        alias = item.child_by_field_name("alias").text.decode("utf-8")
        imported = item.child_by_field_name("name").text.decode("utf-8")
        if alias != name:
            return []
        return [("import", module or imported)]
    if item.type == "dotted_name":
        text = item.text.decode("utf-8")
        bound = text if module is not None else text.split(".")[0]
        if bound != name:
            return []
        return [("import", module or text)]
    return []


def _descendants(node: Node) -> list[Node]:
    found = [node]
    for child in node.named_children:
        found += _descendants(child)
    return found
