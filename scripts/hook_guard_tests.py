#!/usr/bin/env python3
"""PreToolUse hook: while tests are locked, deny edits to test files.

The lock is the file `.groundwork/state/tests-locked`, created by the
implement skill. It is a guardrail that makes test changes deliberate, not
a security boundary: a determined agent could still change a test through a
command this hook does not recognize. The review stage and
detect_workarounds.py catch what slips past.

Only the person removes the lock (`! rm .groundwork/state/tests-locked`),
so this hook also denies agent commands that delete or move it.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import TEST_LOCK, load_config, matches_any, project_root, relative_to_root

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Commands that can change or remove a file named among their arguments.
MUTATING_VERB = re.compile(
    r"(^|[\s;&|(])(rm|mv|cp|tee|truncate|unlink|sed\s+(-[a-zA-Z]*\s+)*-i|perl\s+-[a-z]*i|git\s+(checkout|restore|rm|mv))\b"
)
LOCK_VERB = re.compile(r"(^|[\s;&|(])(rm|mv|unlink|truncate|shred)\b|\s-delete\b")
# Output redirection targets. `2>&1` yields none: a target cannot start with `&`.
REDIRECT_TARGET = re.compile(r"(?<![<>&0-9])[0-9]?>{1,2}\s*([^\s;&|<>()]+)")


def deny(reason: str) -> None:
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


def decide(event: dict, root: Path, config: dict) -> str | None:
    """Return a denial reason, or None to let the tool run."""
    if not (root / TEST_LOCK).exists():
        return None
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}
    globs = config["testGlobs"]

    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        rel = relative_to_root(path, root)
        if rel and matches_any(rel, globs):
            return (
                f"Tests are locked during implementation, so {rel} cannot be edited. "
                "If the test is wrong, stop and tell the user what is wrong with it; "
                "they unlock tests with `! rm .groundwork/state/tests-locked`."
            )
        return None

    if tool == "Bash":
        command = tool_input.get("command", "")
        targets = REDIRECT_TARGET.findall(command)
        if ".groundwork/state" in command and (
            LOCK_VERB.search(command) or any(".groundwork/state" in t for t in targets)
        ):
            return "Only the user removes the test lock. Ask them to run `! rm .groundwork/state/tests-locked`."
        candidates = list(targets)
        if MUTATING_VERB.search(command):
            try:
                candidates += shlex.split(command, posix=True)
            except ValueError:
                candidates += command.split()
        for word in candidates:
            if ("/" in word or "." in word) and matches_any(relative_to_root(word, root), globs):
                return f"Tests are locked; this command could change {word}. Ask the user to unlock tests first."
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    root = project_root(event.get("cwd"))
    config = load_config(root)
    if config is None:
        return 0
    reason = decide(event, root, config)
    if reason:
        deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
