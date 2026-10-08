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
from pathlib import Path


def build_map(root: Path, base: str) -> dict:
    """Return the map as JSON-ready data: base, head, boxes, arrows and notes."""
    return {"base": "", "head": "", "boxes": [], "arrows": [], "notes": {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--post", action="store_true")
    args = parser.parse_args(argv)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "pr-map.json").write_text(json.dumps(build_map(Path.cwd(), args.base)), encoding="utf-8")
        (args.out / "pr-map.md").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
