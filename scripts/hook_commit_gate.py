#!/usr/bin/env python3
"""PreToolUse hook: run the project's checks before Claude commits.

Configured in .groundwork/config.json as one shell command:

    "onCommit": "pnpm lint && pnpm typecheck && pnpm test"

Fires on Bash commands that run `git commit`. Checks run at the commit, not
after every edit, because code is often half-finished mid-change and
checking every intermediate state pushes the agent to silence warnings that
would have resolved themselves.

Skipped when:

- the project has no `onCommit` command;
- nothing outside the spec directory and Markdown files has changed;
- the working tree is identical to the last run that passed.

The checks run on the working tree, not the staged snapshot. CI checks the
commit itself.

On failure the commit is denied and Claude gets the tail of the output.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import STATE_DIR, load_config, project_root

TIMEOUT_S = 840
TAIL_CHARS = 4000
PASS_STAMP = STATE_DIR / "last-commit-pass"
# `git commit`, also with global options such as `git -C dir commit` or `git -c k=v commit`.
GIT_COMMIT = re.compile(r"(^|[\s;&|(])git(\s+-[cC]\s+\S+)*\s+commit(?=$|[\s;&|)])")


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


def gate(command: str, root: Path, config: dict) -> str | None:
    """Run the checks for a commit command. Return a denial reason, or None."""
    check = config.get("onCommit")
    if not check or not GIT_COMMIT.search(command):
        return None
    try:
        paths = changed_code(root, config["specDir"])
    except (OSError, subprocess.CalledProcessError):
        return None
    if not paths:
        return None

    fingerprint = tree_fingerprint(root, paths)
    stamp = root / PASS_STAMP
    if stamp.is_file() and stamp.read_text().strip() == fingerprint:
        return None

    try:
        proc = subprocess.run(
            check, shell=True, cwd=root, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
        ok, output = proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        ok, output = False, f"timed out after {TIMEOUT_S}s"

    if ok:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(fingerprint)
        return None
    return (
        f"Project checks failed (`{check}`), so the commit was not made. Fix the cause, not the check.\n\n"
        + (output[-TAIL_CHARS:])
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    root = project_root(event.get("cwd"))
    config = load_config(root)
    if not config:
        return 0
    reason = gate((event.get("tool_input") or {}).get("command", ""), root, config)
    if reason:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
