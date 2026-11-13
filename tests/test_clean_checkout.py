"""Tests for scripts/clean_checkout.py. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clean_checkout.py"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def clean(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


class CleanCheckoutTests(unittest.TestCase):
    """A bare origin and a clone of it whose main branch is pushed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.origin = base / "origin.git"
        self.clone = base / "clone"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)], check=True, capture_output=True)
        git(self.clone, "config", "user.email", "t@example.com")
        git(self.clone, "config", "user.name", "Test")
        git(self.clone, "checkout", "-q", "-b", "main")
        write(self.clone / ".gitignore", "Intermediate/\n.godot/\n")
        # A tracked folder that shares a build-output name must survive.
        write(self.clone / "Binaries" / "tool.txt")
        write(self.clone / "src.txt")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "init")
        git(self.clone, "push", "-q", "-u", "origin", "main")
        write(self.clone / "Intermediate" / "obj.bin")
        write(self.clone / "greybox" / ".godot" / "cache.bin")

    def tearDown(self):
        self._tmp.cleanup()

    def test_refuses_uncommitted_changes(self):
        """[clean-checkout AC-1] A checkout with uncommitted changes is left as it is."""
        write(self.clone / "src.txt", "edited")
        result = clean(str(self.clone))
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted", result.stderr)
        self.assertIn("src.txt", result.stderr)
        self.assertTrue((self.clone / "Intermediate").exists())

    def test_refuses_unpushed_commits(self):
        """[clean-checkout AC-2] A checkout with commits on no remote is left as it is."""
        write(self.clone / "new.txt")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "local only")
        result = clean(str(self.clone))
        self.assertEqual(result.returncode, 1)
        self.assertIn("not on any remote", result.stderr)
        self.assertIn("local only", result.stderr)
        self.assertTrue((self.clone / "Intermediate").exists())

    def test_deletes_ignored_build_output_only(self):
        """[clean-checkout AC-3] Ignored build folders go; tracked folders with the same names stay."""
        result = clean(str(self.clone))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.clone / "Intermediate").exists())
        self.assertFalse((self.clone / "greybox" / ".godot").exists())
        self.assertTrue((self.clone / "Binaries" / "tool.txt").exists())
        self.assertTrue((self.clone / "src.txt").exists())

    def test_dry_run_deletes_nothing(self):
        """[clean-checkout AC-4] --dry-run lists the folders and deletes none."""
        result = clean(str(self.clone), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Intermediate", result.stdout)
        self.assertTrue((self.clone / "Intermediate").exists())

    def test_remove_deletes_a_linked_worktree(self):
        """[clean-checkout AC-5] --remove on a linked worktree removes it and its registration."""
        tree = self.clone.parent / "tree"
        git(self.clone, "worktree", "add", "-q", "--detach", str(tree), "main")
        write(tree / "Intermediate" / "obj.bin")
        result = clean(str(tree), "--remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(tree.exists())
        self.assertNotIn(tree.as_posix(), git(self.clone, "worktree", "list"))

    def test_remove_deletes_a_clone(self):
        """[clean-checkout AC-6] --remove on a clone deletes its folder."""
        result = clean(str(self.clone), "--remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.clone.exists())


if __name__ == "__main__":
    unittest.main()
