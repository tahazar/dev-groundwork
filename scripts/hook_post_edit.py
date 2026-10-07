#!/usr/bin/env python3
"""PostToolUse hook: run the project's per-file checks after each edit.

Configured in .groundwork/config.json:

    "onEdit": [
      {"glob": "**/*.ts", "run": "pnpm exec oxfmt {file} && pnpm exec oxlint {file}"},
      {"glob": "**/*.py", "run": ".venv/bin/ruff format {file} && .venv/bin/ruff check {file}"}
    ]

`{file}` is replaced with the edited path, shell-quoted and relative to the
project root. Commands run from the project root. On failure the output goes
back to Claude (exit status 2), which sees it and fixes the file.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import glob_match, load_config, project_root, relative_to_root

TIMEOUT_S = 150
TAIL_CHARS = 3000


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    root = project_root(event.get("cwd"))
    config = load_config(root)
    if not config or not config.get("onEdit"):
        return 0
    path = (event.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    rel = relative_to_root(path, root)
    if rel.startswith("/") or not (root / rel).is_file():
        return 0

    for rule in config["onEdit"]:
        if not glob_match(rel, rule["glob"]):
            continue
        command = rule["run"].replace("{file}", shlex.quote(rel))
        try:
            proc = subprocess.run(
                command, shell=True, cwd=root, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
            )
        except subprocess.TimeoutExpired:
            print(f"dev-groundwork: `{command}` timed out after {TIMEOUT_S}s", file=sys.stderr)
            return 2
        if proc.returncode != 0:
            output = (proc.stdout + proc.stderr).strip()[-TAIL_CHARS:]
            print(f"dev-groundwork: `{command}` failed for {rel}:\n{output}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
