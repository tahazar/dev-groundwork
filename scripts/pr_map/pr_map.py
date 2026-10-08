#!/usr/bin/env python3
"""Map the functions a pull request changes, and what calls them and what they call.

Usage:
    pr_map.py --base <ref> [--out DIR] [--post]

--out writes pr-map.json (the map) and pr-map.md (the comment body) to DIR.
--post upserts the pull request comment and writes the job summary, using
the GitHub Actions environment (GITHUB_API_URL, GITHUB_TOKEN,
GITHUB_REPOSITORY, GITHUB_EVENT_PATH, GITHUB_STEP_SUMMARY,
GITHUB_SERVER_URL, GITHUB_RUN_ID).

Design: docs/specs/pr-map/design.md. This file is a stub until the
implementation tasks fill it in; the acceptance tests in tests_pr_map/
define its behaviour.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import constructs
from constructs import Construct, FileConstructs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from groundwork_config import SKIP_DIRS, diff_against, merge_base, project_root

# A -U0 hunk header, "@@ -<base start>,<count> +<head start>,<count> @@". In the
# unified format git writes (GNU diff manual, "Detailed Description of Unified
# Format"), a count left out means one line, and a count of 0 means no lines on
# that side, with the start naming the line the change sits after.
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


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
class FileChange:
    """A changed source file: its path at the base commit and in the working tree, None where it is absent."""

    old: str | None
    new: str | None


def build_map(root: Path, base: str) -> dict:
    """Return the map as JSON-ready data: base, head, boxes, arrows and notes."""
    base_sha = _git_step(f"finding the merge base of {base}", merge_base, root, base)
    head_sha = _git_step("reading the head commit", _git, root, "rev-parse", "HEAD").strip()
    boxes: list[Box] = []
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
        boxes += classify(before, after, deleted, added)
    notes: dict = {}
    if skipped:
        notes["skipped"] = skipped
    if syntax_errors:
        notes["syntax_errors"] = syntax_errors
    return {"base": base_sha, "head": head_sha, "boxes": [asdict(b) for b in boxes], "arrows": [], "notes": notes}


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--post", action="store_true")
    args = parser.parse_args(argv)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "pr-map.json").write_text(json.dumps(build_map(project_root(), args.base)), encoding="utf-8")
        (args.out / "pr-map.md").write_text("", encoding="utf-8")
    return 0


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
    """Run a git helper; on failure raise MapError naming the action, with git's stderr and the cause."""
    try:
        return run(*args)
    except subprocess.CalledProcessError as exc:
        raise MapError(f"{action}: {_reason(exc)}") from exc


def _reason(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return stderr.strip() or str(exc)
    return str(exc)


if __name__ == "__main__":
    raise SystemExit(main())
