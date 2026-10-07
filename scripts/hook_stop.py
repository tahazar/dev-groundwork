#!/usr/bin/env python3
"""Stop hook: run the project's checks before Claude ends a turn.

Configured in .groundwork/config.json as one shell command:

    "onStop": "pnpm typecheck && pnpm test"

Skipped when:

- the stop was already blocked once in this chain (`stop_hook_active`), so a
  failing check cannot loop forever;
- nothing outside the spec directory and Markdown files has changed;
- the working tree is identical to the last run that passed.

On failure the turn is blocked and Claude gets the tail of the output.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import STATE_DIR, load_config, project_root

TIMEOUT_S = 840
TAIL_CHARS = 4000
PASS_STAMP = STATE_DIR / "last-stop-pass"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def changed_code(root: Path, spec_dir: str) -> list[str]:
    """Changed or untracked paths that are not specs or Markdown."""
    paths = []
    for line in git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if path.startswith((spec_dir.rstrip("/") + "/", ".groundwork/")) or path.endswith(".md"):
            continue
        paths.append(path)
    return paths


def tree_fingerprint(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256(git(root, "diff", "HEAD", "--no-color").encode())
    for path in sorted(paths):
        p = root / path
        if p.is_file():
            digest.update(path.encode())
            digest.update(p.read_bytes())
    return digest.hexdigest()


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("stop_hook_active"):
        return 0
    root = project_root(event.get("cwd"))
    config = load_config(root)
    if not config or not config.get("onStop"):
        return 0
    try:
        paths = changed_code(root, config["specDir"])
    except (OSError, subprocess.CalledProcessError):
        return 0
    if not paths:
        return 0

    fingerprint = tree_fingerprint(root, paths)
    stamp = root / PASS_STAMP
    if stamp.is_file() and stamp.read_text().strip() == fingerprint:
        return 0

    command = config["onStop"]
    try:
        proc = subprocess.run(
            command, shell=True, cwd=root, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
        ok, output = proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        ok, output = False, f"timed out after {TIMEOUT_S}s"

    if ok:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(fingerprint)
        return 0
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": f"Project checks failed (`{command}`). Fix the cause, not the check.\n\n"
                + output[-TAIL_CHARS:],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
