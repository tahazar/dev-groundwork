#!/usr/bin/env python3
"""Flag changes that make checks pass without doing the work.

Scans the diff between a base ref and the working tree for:

- skipped or focused tests (`it.skip`, `.only`, `xit`, `pytest.mark.skip`, ...);
- lint suppressions (`oxlint-disable`, `eslint-disable`, `# noqa`, ...);
- type-check suppressions (`@ts-ignore`, `# type: ignore`, ...);
- coverage exclusions (`istanbul ignore`, `pragma: no cover`, ...);
- any edit to a line that sets a coverage threshold;
- deleted test files.

Markdown and other prose files are skipped, since documentation names these
patterns without using them.

A flagged line passes when it carries `groundwork-allow: <reason>`; the
reason is printed so a reviewer can judge it.

Exit status: 0 when nothing unallowed is found, 1 otherwise, 2 on errors.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import DEFAULTS, load_config, matches_any, project_root

ALLOW = re.compile(r"groundwork-allow:\s*(\S.*)")

# Applied to added lines.
ADDED_PATTERNS: dict[str, str] = {
    "test-skip": r"\b(?:it|test|describe|context)\.(?:skip|only|todo)\b|\bx(?:it|describe|test)\s*\(|"
    r"@pytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\s*\(|@unittest\.skip|\bt\.Skip\(",
    "lint-suppression": r"(?:eslint|oxlint)-disable|biome-ignore|#\s*noqa\b|pylint:\s*disable|\bNOLINT\b|"
    r"#\[allow\(|@SuppressWarnings",
    "type-suppression": r"@ts-(?:ignore|expect-error|nocheck)\b|#\s*type:\s*ignore|pyright:\s*ignore|mypy:\s*ignore",
    "coverage-exclusion": r"(?:istanbul|c8|v8)\s+ignore|pragma:\s*no\s*cover|#\s*nocov\b",
}
# Applied to added and removed lines: any edit to a threshold is worth a look.
CHANGED_PATTERNS: dict[str, str] = {
    "threshold-change": r"\b(?:thresholds?|fail_under|coverageThreshold|minimum_coverage)\b[\"']?\s*[:=]"
    r"|--cov-fail-under",
}
# In coverage config files, per-metric floors inside a thresholds block count too.
COVERAGE_CONFIGS = ["**/vitest.config.*", "**/jest.config.*", "**/.nycrc*", "**/.coveragerc", "**/codecov.yml"]
METRIC_FLOOR = r"\b(?:lines|branches|functions|statements)\b\s*:\s*\d"
# Prose describes these patterns without using them.
DOC_FILES = ["**/*.md", "**/*.mdx", "**/*.rst", "**/*.txt"]


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def scan_diff(diff: str, ignore: list[str], extra: dict[str, str]) -> list[tuple[str, str, str, str | None]]:
    """Return (kind, file, line, allow reason) for each flagged diff line."""
    added = {**ADDED_PATTERNS, **extra}
    findings = []
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = None if line[4:] == "/dev/null" else line[4:].removeprefix("b/")
            continue
        if line.startswith("--- ") or current is None or matches_any(current, ignore + DOC_FILES):
            continue
        if line.startswith("+"):
            sign, body = "+", line[1:]
        elif line.startswith("-"):
            sign, body = "-", line[1:]
        else:
            continue
        changed = dict(CHANGED_PATTERNS)
        if matches_any(current, COVERAGE_CONFIGS):
            changed["threshold-change-metric"] = METRIC_FLOOR
        patterns = {**added, **changed} if sign == "+" else changed
        for kind, pattern in patterns.items():
            if re.search(pattern, body):
                allow = ALLOW.search(body)
                findings.append((kind, current, f"{sign} {body.strip()}", allow.group(1) if allow else None))
    return findings


def deleted_tests(root: Path, base: str, test_globs: list[str]) -> list[str]:
    out = git(root, "diff", "--name-status", "--no-renames", base)
    return [
        name
        for status, name in (line.split("\t", 1) for line in out.splitlines() if "\t" in line)
        if status == "D" and matches_any(name, test_globs)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="ref to compare against (default origin/main)")
    args = parser.parse_args(argv)

    root = project_root()
    config = load_config(root) or DEFAULTS
    workarounds = config.get("workarounds", {})
    ignore = list(workarounds.get("ignorePaths", []))
    extra = {f"extra-{i}": p for i, p in enumerate(workarounds.get("extraPatterns", []))}

    try:
        base = git(root, "merge-base", args.base, "HEAD").strip()
        diff = git(root, "diff", "--unified=0", "--no-color", base)
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2

    findings = scan_diff(diff, ignore, extra)
    findings += [
        ("deleted-test", name, "file deleted", None) for name in deleted_tests(root, base, config["testGlobs"])
    ]

    blocking = 0
    for kind, path, text, allow in findings:
        if allow:
            print(f"allowed  {kind:18} {path}: {text}  (reason: {allow})")
        else:
            blocking += 1
            print(f"FLAGGED  {kind:18} {path}: {text}")
    if not findings:
        print("no workarounds found")
    elif blocking:
        print(
            f"\n{blocking} flagged change(s). Fix them, or add `groundwork-allow: <reason>` "
            "on the line if the change is intended."
        )
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
