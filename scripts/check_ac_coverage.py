#!/usr/bin/env python3
"""Check that every acceptance criterion in a feature has a tagged test.

Criteria are read from `<specDir>/<feature>/requirements.md`, from list items
that start with a bold ID:

    - **AC-1** When a clip is selected, the system shall ...
    - **AC-2** (deferred) When ...

Tests are matched by a tag in the test name or a comment next to it:

    it("[arp-engine AC-1] keeps the step counter across chords", ...)
    def test_rejects_empty_input():  # [arp-engine AC-2]

The tag carries the feature name so IDs stay unique across features.
Criteria marked `(deferred)` are reported but not required.

With `--changed-since REF`, checks every feature whose spec files changed
since REF and whose requirements are approved (`- Status: approved`).

Exit status: 0 when every required criterion has a test and no test cites a
criterion that does not exist, 1 otherwise, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import diff_against, load_config, matches_any, merge_base, project_root, walk_files

AC_LINE = re.compile(r"^\s*[-*]\s+\*\*(AC-\d+)\*\*(.*)$")


def read_criteria(requirements: Path) -> tuple[list[str], list[str]]:
    required, deferred = [], []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        m = AC_LINE.match(line)
        if m:
            (deferred if "(deferred)" in m.group(2).lower() else required).append(m.group(1))
    return required, deferred


def find_tags(root: Path, feature: str, test_globs: list[str]) -> dict[str, list[str]]:
    """Map each AC ID to the test files that tag it."""
    tag = re.compile(r"\[" + re.escape(feature) + r"\s+(AC-\d+)\]")
    found: dict[str, list[str]] = {}
    for path in walk_files(root):
        rel = path.relative_to(root).as_posix()
        if not matches_any(rel, test_globs):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for ac in tag.findall(text):
            found.setdefault(ac, []).append(rel)
    return found


def check_feature(root: Path, config: dict, feature: str) -> int:
    requirements = root / config["specDir"] / feature / "requirements.md"
    if not requirements.is_file():
        print(f"not found: {requirements}", file=sys.stderr)
        return 2

    required, deferred = read_criteria(requirements)
    if not required and not deferred:
        print(
            f"{requirements}: no acceptance criteria found (expected lines like '- **AC-1** When ...')", file=sys.stderr
        )
        return 1
    tags = find_tags(root, feature, config["testGlobs"])

    failed = False
    print(f"{feature}:")
    for ac in required:
        files = sorted(set(tags.get(ac, [])))
        if files:
            print(f"  covered    {ac}  {', '.join(files)}")
        else:
            print(f"  MISSING    {ac}  no test tagged [{feature} {ac}]")
            failed = True
    for ac in deferred:
        print(f"  deferred   {ac}")
    for ac in sorted(set(tags) - set(required) - set(deferred)):
        print(f"  UNKNOWN    {ac}  tagged in {', '.join(sorted(set(tags[ac])))} but not in requirements.md")
        failed = True
    return 1 if failed else 0


def approved_features_changed_since(root: Path, config: dict, base: str) -> list[str]:
    """Features with changes since `base` whose requirements are approved."""
    spec_dir = config["specDir"].rstrip("/")
    names = diff_against(root, merge_base(root, base), "--name-only", "--", spec_dir).splitlines()
    features = sorted({n[len(spec_dir) + 1 :].split("/", 1)[0] for n in names if n.startswith(spec_dir + "/")})
    approved = []
    for feature in features:
        req = root / spec_dir / feature / "requirements.md"
        if req.is_file() and re.search(r"^- Status: approved", req.read_text(encoding="utf-8"), re.MULTILINE):
            approved.append(feature)
    return approved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("feature", nargs="?", help="feature directory name under specDir")
    target.add_argument("--changed-since", metavar="REF", help="check every approved feature changed since REF")
    args = parser.parse_args(argv)

    root = project_root()
    config = load_config(root)
    if config is None:
        print("no .groundwork/config.json in this project; run /dev-groundwork:setup", file=sys.stderr)
        return 2
    if args.feature:
        return check_feature(root, config, args.feature)
    features = approved_features_changed_since(root, config, args.changed_since)
    if not features:
        print("no approved features changed")
        return 0
    return max(check_feature(root, config, f) for f in features)


if __name__ == "__main__":
    sys.exit(main())
