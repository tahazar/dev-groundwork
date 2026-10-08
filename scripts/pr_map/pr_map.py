#!/usr/bin/env python3
"""Map the functions a pull request changes, and what calls them and what they call.

Usage:
    pr_map.py --base <ref> [--out DIR] [--post]

--out writes pr-map.json (the map) and pr-map.md (the comment body) to DIR.
--post upserts the pull request comment and writes the job summary, using
the GitHub Actions environment (GITHUB_API_URL, GITHUB_TOKEN,
GITHUB_REPOSITORY, GITHUB_EVENT_PATH, GITHUB_STEP_SUMMARY,
GITHUB_SERVER_URL, GITHUB_RUN_ID).

Design: docs/specs/pr-map/design.md. build_map runs Pipeline steps 1 to 6:
the boxes, then the arrows between them and their neighbours (connect).
render writes the comment body and its shorter versions (step 8), and
github posts it and writes the job summary (step 9). main is step 10: with
--post, any failure is posted and the exit code is 0.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import constructs
import github
import render
import resolve
from constructs import Construct, FileConstructs, Site
from resolve import CALLEE, CALLER, REMOVED, Answer, Candidate, Code, Resolver, ResolverError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from groundwork_config import SKIP_DIRS, diff_against, merge_base, project_root

# A -U0 hunk header, "@@ -<base start>,<count> +<head start>,<count> @@". In the
# unified format git writes (GNU diff manual, "Detailed Description of Unified
# Format"), a count left out means one line, and a count of 0 means no lines on
# that side, with the start naming the line the change sits after.
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)

# The name of a module box: a reference outside every construct belongs to its file (design, data model).
MODULE = "<module>"
# A constructor's own name; its callers write the class's name instead (design, step 5).
CONSTRUCTORS = {".py": ("__init__", "__new__"), ".ts": ("constructor",), ".tsx": ("constructor",)}

log = logging.getLogger("pr_map")


class MapError(RuntimeError):
    """A step of building the map failed; the message names the step and keeps git's reason."""


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


@dataclass(frozen=True)
class FileChange:
    """A changed source file: its path at the base commit and in the working tree, None where it is absent."""

    old: str | None
    new: str | None


def build_map(root: Path, base: str, node: str = "node") -> dict:
    """Return the map as JSON-ready data: base, head, boxes, arrows and notes.

    node is the Node executable the TypeScript resolver runs on.
    """
    base_sha = _git_step(f"finding the merge base of {base}", merge_base, root, base)
    head_sha = _git_step("reading the head commit", _git, root, "rev-parse", "HEAD").strip()
    boxes: list[Box] = []
    gone: list[Construct] = []  # the base-commit constructs of removed boxes
    skipped: list[dict] = []
    syntax_errors: list[dict] = []
    name_status = _git_step(
        f"listing the files changed since {base_sha}", diff_against, root, base_sha, "--name-status", "-M", "-z"
    )
    for change in parse_name_status(name_status):
        # A file that cannot be read on either side is left out whole, so half a
        # pair cannot show every construct as added or removed (AC-19).
        try:
            before = _parse_base(root, base_sha, change.old) if change.old else None
        except (subprocess.CalledProcessError, constructs.UnreadableSource) as exc:
            skipped.append({"path": change.new or change.old, "reason": f"base version: {_reason(exc)}"})
            continue
        try:
            after = constructs.parse(change.new, (root / change.new).read_bytes()) if change.new else None
        except (OSError, constructs.UnreadableSource) as exc:
            skipped.append({"path": change.new, "reason": _reason(exc)})
            continue
        if after is not None and after.error_lines:
            syntax_errors.append({"path": after.path, "lines": list(after.error_lines)})
        deleted: set[int] = set()
        added: set[int] = set()
        if before is not None and after is not None:
            diff = _git_step(
                f"diffing {change.new} against {base_sha}",
                diff_against,
                root,
                base_sha,
                "-U0",
                "-M",
                "--no-color",
                "--no-ext-diff",
                "--",
                *dict.fromkeys((change.old, change.new)),
            )
            deleted, added = parse_hunks(diff)
        found = classify(before, after, deleted, added)
        removed = {b.id for b in found if b.status == "removed"}
        gone += [c for c in before.constructs if c.id in removed] if before else []
        boxes += found
    files, unreadable = constructs.scan(root)
    listed = {s["path"] for s in skipped}
    skipped += [{"path": path, "reason": reason} for path, reason in sorted(unreadable.items()) if path not in listed]
    resolver = Resolver(root, node)
    try:
        arrows, neighbours, graph_notes = connect(root, files, boxes, gone, resolver)
    finally:
        resolver.close()
    notes: dict = {}
    if skipped:
        notes["skipped"] = skipped
    if syntax_errors:
        notes["syntax_errors"] = syntax_errors
    notes.update(graph_notes)
    return {
        "base": base_sha,
        "head": head_sha,
        "boxes": [asdict(b) for b in boxes + neighbours],
        "arrows": [asdict(a) for a in arrows],
        "notes": notes,
    }


def connect(
    root: Path, files: dict[str, FileConstructs], boxes: list[Box], gone: list[Construct], resolver: Resolver
) -> tuple[list[Arrow], list[Box], dict]:
    """Arrows to and from the boxes, the neighbour boxes they reach, and the text section's notes.

    Design, Pipeline steps 5 and 6. files are every source file in the head
    tree; gone are the base-commit constructs of the removed boxes.
    """
    failures: list[dict] = []
    code = _code(root, files, boxes, gone, resolver, failures)
    candidates = Candidates(files, code)
    for box in boxes:
        target = code.constructs[box.id]
        if box.status == "removed":
            candidates.callers(target, REMOVED, ())
            continue
        try:
            found = resolver.references(target.path, target.line, target.column)
        except ResolverError as exc:
            # jedi stopping early, or the TypeScript fallback: the name matches still give the callers.
            log.warning("searching references to %s: %s", target.id, exc)
            failures.append({"at": _at(target.path, target.line, target.column), "reason": str(exc)})
            found = []
        candidates.callers(target, CALLER, found)
        candidates.callees(target)

    answers = Answers(resolver)
    live: dict[str, list[str]] = defaultdict(list)  # match key -> live construct ids, for unresolved callees
    defined = set(code.positions.values())
    for c in code.constructs.values():
        if c.id in defined:
            live[_short(c)].append(c.id)
    arrows: dict[tuple[str, str, str], Arrow] = {}
    notes: dict[str, dict[str, dict]] = defaultdict(dict)  # kind -> site -> entry: one entry per site
    library: Counter[str] = Counter()
    library_sites: set[str] = set()
    for candidate, source in candidates.items():
        at = _at(candidate.path, candidate.line, candidate.column)
        v = resolve.verdict(candidate, answers.at(candidate), code, live.get(candidate.name, ()))
        if v.certainty:
            key = (source, v.target, at)
            if key not in arrows or arrows[key].certainty == "possible":
                arrows[key] = Arrow(source, v.target, v.certainty, at, v.reason)
        elif v.note == "library" and candidate.call and at not in library_sites:
            # Counted once per call: `np` in `np.mean(xs)` is the same library call as `mean`.
            library_sites.add(at)
            library[candidate.path] += 1
        elif v.note == "refers" and v.refers_to != f"{candidate.path}:{candidate.line}":
            # The site's own line is where the attribute is assigned (`self.notes = ...`): nothing to point to.
            notes["refers"][at] = {"at": at, "source": source, "name": candidate.name, "refers_to": v.refers_to}
        elif v.note == "unresolved" and v.options:
            notes["unresolved"][at] = {
                "at": at,
                "source": source,
                "name": candidate.name,
                "reason": v.reason,
                "options": list(v.options),
            }
        elif v.note == "removed constructor":
            notes["removed_constructor_calls"][at] = {"at": at, "source": source, "target": v.target}

    ordered = sorted(arrows.values(), key=lambda a: (a.source, a.target, a.at))
    present = {b.id for b in boxes}
    neighbours: dict[str, Box] = {}
    for a in ordered:
        for end in (a.source, a.target):
            if end not in present and end not in neighbours:
                neighbours[end] = _neighbour(end, code)
    result: dict = {kind: list(entries.values()) for kind, entries in notes.items()}
    if library:
        result["library_calls"] = [{"path": path, "count": n} for path, n in sorted(library.items())]
    if failures:
        result["resolver_failures"] = failures
    if resolver.typescript_failure:
        result["typescript_fallback"] = resolver.typescript_failure
    return ordered, list(neighbours.values()), result


class Candidates:
    """Reference sites that may refer to a box, by role (design, step 5), each with its arrow's source.

    A site found twice for the same target is one candidate; `referenced`
    is kept when either finding came from the target's own findReferences.
    """

    def __init__(self, files: dict[str, FileConstructs], code: Code):
        self.code = code
        self._found: dict[tuple, tuple[Candidate, str]] = {}
        self._at: dict[tuple[str, int, int], Site] = {}
        self._named: dict[str, list[tuple[str, Site]]] = defaultdict(list)
        self._owned: dict[str, list[tuple[str, Site]]] = defaultdict(list)
        for file in files.values():
            for site in file.sites:
                self._at[(file.path, site.line, site.column)] = site
                self._named[site.name].append((file.path, site))
                if site.owner is not None:
                    self._owned[site.owner].append((file.path, site))

    def items(self) -> list[tuple[Candidate, str]]:
        return list(self._found.values())

    def callers(self, target: Construct, role: str, references) -> None:
        """Candidates for target's callers: name matches, the resolver's references, aliases, and `cls(...)`."""
        keys, runners = self._keys(target)
        typescript = Path(target.path).suffix in resolve.TYPESCRIPT
        for key in keys:
            for path, site in self._named.get(key, ()):
                self._caller(path, site, target, role, referenced=False)
        for loc in references:
            site = self._at.get((loc.path, loc.line, loc.column)) if loc.path is not None else None
            if site is not None:
                self._caller(loc.path, site, target, role, referenced=typescript)
        if role == CALLER and runners:
            for path, site in self._named.get("cls", []) + self._named.get("type", []):
                if site.runtime and self._inside(site.owner, runners):
                    candidate = Candidate(path, site.line, site.column, site.name, True, role, target.id, site.runtime)
                    self._add(candidate, site.owner or _module_id(path))

    def callees(self, box: Construct) -> None:
        """Every identifier inside the box's own span, nested constructs left out (design, step 4)."""
        for path, site in self._owned.get(box.id, ()):
            if not site.imported:
                self._add(Candidate(path, site.line, site.column, site.name, site.call, CALLEE), box.id)

    def _caller(self, path: str, site: Site, target: Construct, role: str, referenced: bool) -> None:
        if site.imported:
            # An import line draws no arrow; the uses of the name it renames to are candidates (design, step 5).
            if site.alias:
                for other_path, other in self._named.get(site.alias, ()):
                    if other_path == path and not other.imported:
                        self._caller(path, other, target, role, referenced=False)
            return
        candidate = Candidate(path, site.line, site.column, site.name, site.call, role, target.id, "", referenced)
        self._add(candidate, site.owner or _module_id(path))

    def _add(self, candidate: Candidate, source: str) -> None:
        key = (candidate.path, candidate.line, candidate.column, candidate.role, candidate.target)
        known = self._found.get(key)
        if known is not None and (known[0].referenced or not candidate.referenced) and not candidate.through:
            return
        if known is not None:
            candidate = replace(candidate, referenced=candidate.referenced or known[0].referenced)
        self._found[key] = (candidate, source)

    def _keys(self, target: Construct) -> tuple[set[str], set[str]]:
        """The target's match keys, and for a Python constructor the ids of its runner classes."""
        keys = {_short(target)}
        cls = self.code.constructs.get(target.parent or "")
        if cls is None or cls.kind != "class" or _short(target) not in CONSTRUCTORS.get(Path(target.path).suffix, ()):
            return keys, set()
        keys.add(_short(cls))
        if Path(target.path).suffix != ".py":
            return keys, set()  # findReferences finds subclass calls, `super(...)` and `new this` (C62)
        runners = set(resolve.runners(cls.id, _short(target), self.code))
        keys.update(self.code.constructs[r].name.rsplit(".", 1)[-1] for r in runners if r in self.code.constructs)
        return keys, runners

    def _inside(self, owner: str | None, classes: set[str]) -> bool:
        """Whether a site's innermost construct is, or sits inside, one of classes."""
        while owner is not None:
            if owner in classes:
                return True
            owner = self.code.constructs[owner].parent if owner in self.code.constructs else None
        return False


class Answers:
    """The resolver's answer at each site, asked once per site (design, step 6)."""

    def __init__(self, resolver: Resolver):
        self.resolver = resolver
        self._cache: dict[tuple[str, int, int], Answer] = {}

    def at(self, candidate: Candidate) -> Answer:
        key = (candidate.path, candidate.line, candidate.column)
        if key not in self._cache:
            self._cache[key] = self._ask(*key)
        return self._cache[key]

    def _ask(self, path: str, line: int, column: int) -> Answer:
        try:
            locations = tuple(self.resolver.definition_at(path, line, column))
            # Only an empty or import-only answer (C56, C57) needs the import traced: library or not.
            if all(loc.kind == "alias" for loc in locations) or not locations:
                return Answer(locations, traced=self.resolver.trace_import(path, line, column))
            return Answer(locations)
        except ResolverError as exc:
            return Answer(error=str(exc))


def _code(
    root: Path,
    files: dict[str, FileConstructs],
    boxes: list[Box],
    gone: list[Construct],
    resolver: Resolver,
    failures: list[dict],
) -> Code:
    """What the verdicts know: constructs, name positions, Python class bases and TypeScript structural matches."""
    by_id, positions = resolve.index(files.values())
    for c in gone:
        by_id.setdefault(c.id, c)
    present = set(positions.values())
    live = [c for c in by_id.values() if c.id in present]
    bases = {c.id: _class_bases(root, c, positions, resolver, failures) for c in live if c.kind == "class" and c.bases}
    implements = {}
    for box in boxes:
        c = by_id[box.id]
        if box.status == "removed" or c.kind != "method" or Path(c.path).suffix not in resolve.TYPESCRIPT:
            continue
        try:
            implements[c.id] = resolver.structural(c, live)
        except ResolverError as exc:
            # The TypeScript fallback: no structural matches, so callers through an interface are possible arrows
            # only when findReferences linked them; resolver_failures and typescript_fallback say why.
            log.warning("matching %s to interfaces: %s", c.id, exc)
            failures.append({"at": _at(c.path, c.line, c.column), "reason": str(exc)})
    return Code(by_id, positions, bases, implements)


def _class_bases(
    root: Path, c: Construct, positions: dict, resolver: Resolver, failures: list[dict]
) -> tuple[str, ...]:
    """A Python class's bases (Resolver.class_bases).

    Fallback: when jedi fails on a base, every base keeps the name the
    source gives it, which reads as a class outside the repository, as
    class_bases does for a base jedi cannot place. Its constructor's
    callers then become possible arrows instead of being dropped.
    """
    try:
        return resolver.class_bases(c, positions)
    except ResolverError as exc:
        log.warning("resolving the bases of %s: %s; using their names as written", c.id, exc)
        failures.append({"at": _at(c.path, c.line, c.column), "reason": str(exc)})
        lines = (root / c.path).read_text(encoding="utf-8").split("\n")
        return tuple(re.match(r"\w*", lines[line - 1][column:]).group(0) for line, column in c.bases)


def _neighbour(box_id: str, code: Code) -> Box:
    path, _, name = box_id.partition("::")
    if name == MODULE:
        return Box(id=box_id, kind="module", name=Path(path).name, path=path, line=1, column=0, status="neighbour")
    return _box(code.constructs[box_id], "neighbour")


def _module_id(path: str) -> str:
    return f"{path}::{MODULE}"


def _short(c: Construct) -> str:
    """The last segment of a construct's name: `m` for `C.m`."""
    return c.name.rsplit(".", 1)[-1]


def _at(path: str, line: int, column: int) -> str:
    return f"{path}:{line}:{column}"


def parse_name_status(text: str) -> list[FileChange]:
    """Changed TypeScript and Python files from `git diff --name-status -M -z`, outside the skip list.

    A rename pairs the two paths. A side whose path is not a supported
    source file counts as absent, so renaming `a.py` to `a.txt` removes a.py's
    constructs.
    """
    fields = text.split("\0")
    changes = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status[0] in "RC":
            old, new = fields[index + 1], fields[index + 2]
            index += 3
        else:
            old = new = fields[index + 1]
            index += 2
        if status[0] == "A":
            old = None
        if status[0] == "D":
            new = None
        old, new = _source(old), _source(new)
        if old or new:
            changes.append(FileChange(old, new))
    return changes


def parse_hunks(diff: str) -> tuple[set[int], set[int]]:
    """Deleted base lines and added head lines (1-based) from a `git diff -U0` of one file."""
    deleted: set[int] = set()
    added: set[int] = set()
    for match in HUNK.finditer(diff):
        old_start, old_count, new_start, new_count = match.groups()
        deleted.update(range(int(old_start), int(old_start) + int(old_count or 1)))
        added.update(range(int(new_start), int(new_start) + int(new_count or 1)))
    return deleted, added


def owners(found: tuple[Construct, ...], lines: set[int]) -> set[str]:
    """Ids of the innermost constructs containing the lines; a line outside every construct has no owner."""
    depth: dict[str, int] = {}
    for c in found:  # source order: a parent comes before what it contains
        depth[c.id] = depth[c.parent] + 1 if c.parent else 0
    result = set()
    for line in lines:
        inside = [c for c in found if c.start_line <= line <= c.end_line]
        if inside:
            result.add(max(inside, key=lambda c: depth[c.id]).id)
    return result


def classify(
    before: FileConstructs | None, after: FileConstructs | None, deleted: set[int], added: set[int]
) -> list[Box]:
    """Boxes for one file's changed, added and removed constructs (design, Pipeline steps 3 and 4).

    Constructs pair by qualified name and ordinal, not path, so a renamed
    file's constructs pair across the rename. A construct is changed when an
    added line's innermost construct is it in the head version, or a deleted
    line's is it in the base version.
    """
    old = {_key(c): c for c in before.constructs} if before else {}
    new = {_key(c): c for c in after.constructs} if after else {}
    touched = owners(after.constructs, added) if after else set()
    touched |= owners(before.constructs, deleted) if before else set()
    boxes = []
    for key, c in new.items():
        if key not in old:
            boxes.append(_box(c, "added"))
        elif c.id in touched or old[key].id in touched:
            boxes.append(_box(c, "changed"))
    boxes += [_box(c, "removed") for key, c in old.items() if key not in new]
    return boxes


def main(argv: list[str] | None = None) -> int:
    """Build the map; write --out files; with --post, comment and write the summary (design, steps 9 and 10).

    Without --post, a missing --base or a failing git exits 2. With --post every
    failure is reported on the pull request and the exit code is 0 (AC-20, AC-21).
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--post", action="store_true")
    args = parser.parse_args(argv)
    if args.post:
        return _post(args)
    if args.base is None:
        parser.error("the following arguments are required: --base")
    try:
        data = build_map(project_root(), args.base)
    except MapError as exc:
        print(f"pr-map: {exc}", file=sys.stderr)
        return 2
    _write_out(args.out, data, render.render_comment(data, ""))
    return 0


def _post(args: argparse.Namespace) -> int:
    """The --post path: always exits 0, so the map never fails a pull request's checks (AC-21)."""
    try:
        ctx = github.context(os.environ)
    except github.ContextError as exc:
        # Nothing can be posted or summarised without the Actions environment; the log is all there is.
        log.error("pr-map cannot post: %s", exc)
        return 0
    try:
        if args.base is None:
            raise MapError("reading the arguments: --base is required")
        data = build_map(project_root(), args.base)
        data["head"] = ctx.head_sha  # the pull request's head commit, not GitHub's merge commit (AC-17)
        versions = render.comment_versions(data, ctx.run_url)
        _write_out(args.out, data, versions[0])
    except MapError as exc:
        log.error("pr-map could not build the map: %s", exc)
        versions = [f"pr-map could not build the map: {exc}"]
    except Exception as exc:
        # The top-level catch (design, step 10): whatever is left is posted as the map's failure.
        log.exception("pr-map could not build the map")
        versions = [f"pr-map could not build the map: {exc}"]
    try:
        log.info("%s", github.publish(ctx, versions))
    except Exception:
        log.exception("pr-map could not post the map")
    return 0


def _write_out(out: Path | None, data: dict, comment: str) -> None:
    """Write pr-map.json (the map) and pr-map.md (the complete comment) to out, the artifact's directory."""
    if out is None:
        return
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "pr-map.json").write_text(json.dumps(data), encoding="utf-8")
        (out / "pr-map.md").write_text(comment, encoding="utf-8")
    except OSError as exc:
        raise MapError(f"writing the map to {out}: {exc}") from exc


def _source(path: str | None) -> str | None:
    if path is None or not constructs.supported(path) or SKIP_DIRS.intersection(Path(path).parts[:-1]):
        return None
    return path


def _key(c: Construct) -> str:
    """Qualified name and ordinal: the construct's identity within its file."""
    return c.id.removeprefix(c.path + "::")


def _box(c: Construct, status: str) -> Box:
    return Box(id=c.id, kind=c.kind, name=c.name, path=c.path, line=c.line, column=c.column, status=status)


def _parse_base(root: Path, base: str, path: str) -> FileConstructs:
    source = subprocess.run(["git", "show", f"{base}:{path}"], cwd=root, capture_output=True, check=True).stdout
    return constructs.parse(path, source)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def _git_step(action: str, run, *args):
    """Run a git helper; on failure, or with git missing, raise MapError naming the action and keeping the cause."""
    try:
        return run(*args)
    except subprocess.CalledProcessError as exc:
        raise MapError(f"{action}: {_reason(exc)}") from exc
    except OSError as exc:
        raise MapError(f"{action}: cannot run git: {exc}") from exc


def _reason(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return stderr.strip() or str(exc)
    return str(exc)


if __name__ == "__main__":
    raise SystemExit(main())
