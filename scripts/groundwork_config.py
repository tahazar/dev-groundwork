"""Shared helpers for the dev-groundwork scripts: project root, config, globs.

Standard library only, so the scripts run in any project and in CI without
installing anything.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from pathlib import Path

CONFIG_PATH = Path(".groundwork") / "config.json"
STATE_DIR = Path(".groundwork") / "state"
TEST_LOCK = STATE_DIR / "tests-locked"

DEFAULTS: dict = {
    "specDir": "docs/specs",
    "testGlobs": [
        "**/test/**",
        "**/tests/**",
        "**/__tests__/**",
        "**/*.test.*",
        "**/*.spec.*",
        "**/*_test.*",
        "**/test_*.py",
    ],
    "onEdit": [],
    "onStop": None,
    "sources": {"tier1": [], "tier2": []},
    "workarounds": {"ignorePaths": [], "extraPatterns": []},
}

# Directories never worth scanning for tests or sources.
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".venv", "venv", "__pycache__"}


def project_root(start: str | os.PathLike | None = None) -> Path:
    """The project root: $CLAUDE_PROJECT_DIR, else the git top level, else cwd."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    cwd = Path(start or os.getcwd()).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return cwd


def load_config(root: Path) -> dict | None:
    """The project's merged config, or None when the project has not opted in.

    Hooks call this first and do nothing when it returns None, so enabling the
    plugin globally has no effect on projects without .groundwork/config.json.
    """
    path = root / CONFIG_PATH
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        user = json.load(fh)
    merged = json.loads(json.dumps(DEFAULTS))
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def glob_match(path: str, pattern: str) -> bool:
    """fnmatch with a leading `**/` also matching at the root.

    fnmatch's `*` already crosses `/`, so `**/test/**` matches nested paths;
    the extra check makes it match `test/x.py` at the top level too.
    """
    path = path.replace(os.sep, "/")
    while path.startswith("./"):
        path = path[2:]
    if fnmatch.fnmatch(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(glob_match(path, p) for p in patterns)


def relative_to_root(path: str, root: Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = (root / p).resolve()
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name
