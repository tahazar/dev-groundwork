"""Tests for pr_map.py when its packages are not installed (the workflow's install step failed; design, step 10).

Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
from helpers import MapRepo
from unit_github import REPO, Server

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pr_map" / "pr_map.py"
# A None entry in sys.modules makes importing that module raise ModuleNotFoundError (Python reference, "The
# module cache"), as if the install step had not installed it.
BLOCKED = ["tree_sitter", "tree_sitter_python", "tree_sitter_typescript", "jedi"]
RUN = (
    "import runpy, sys\n"
    f"sys.modules.update(dict.fromkeys({BLOCKED!r}))\n"
    f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
    f"sys.argv = [{str(SCRIPT)!r}, *sys.argv[1:]]\n"
    f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
)
MESSAGE = "pr-map could not build the map: missing package tree_sitter_python (the install step may have failed)"


class MissingPackageTests(unittest.TestCase):
    def run_map(self, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", RUN, *args],
            cwd=ROOT,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_missing_package_is_posted_with_post(self):
        server = Server()
        self.addCleanup(server.close)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        event = {
            "pull_request": {
                "number": 5,
                "head": {"sha": "abc", "repo": {"full_name": REPO}},
                "base": {"repo": {"full_name": REPO}},
            }
        }
        (tmp / "event.json").write_text(json.dumps(event), encoding="utf-8")
        env = {
            "GITHUB_API_URL": server.url,
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_EVENT_PATH": str(tmp / "event.json"),
            "GITHUB_STEP_SUMMARY": str(tmp / "summary.md"),
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "7",
        }
        done = self.run_map(["--base", "base", "--post"], env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(server.comments), 1, done.stderr)
        self.assertIn(MESSAGE, server.comments[0]["body"])
        self.assertIn(MESSAGE, (tmp / "summary.md").read_text(encoding="utf-8"))

    def test_missing_package_exits_2_without_post(self):
        done = self.run_map(["--base", "base"], {})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("missing package tree_sitter_python (the install step may have failed)", done.stderr)
        self.assertIn("cannot import its packages", done.stderr)  # the warning

    def test_installed_packages_build_the_map_without_the_warning(self):
        repo = MapRepo()
        self.addCleanup(repo.close)
        repo.base({"lib.py": "def f():\n    return 1\n"})
        repo.head({"lib.py": "def f():\n    return 2\n"})
        with self.assertNoLogs("pr_map", "WARNING"):
            built = repo.build()
        self.assertEqual(built.code, 0)
        self.assertIsNotNone(built.box("lib.py", "f"))


if __name__ == "__main__":
    unittest.main()
