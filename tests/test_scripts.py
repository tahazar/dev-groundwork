"""Tests for the dev-groundwork scripts. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_ac_coverage  # noqa: E402
import check_citations  # noqa: E402
import detect_workarounds  # noqa: E402
import hook_commit_gate  # noqa: E402
import hook_guard_tests  # noqa: E402
from groundwork_config import glob_match, load_config  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class Repo:
    """A throwaway git repository with a .groundwork/config.json."""

    def __init__(self, config: dict | None = None):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        self.write(".groundwork/config.json", json.dumps(config or {}))
        self.commit("init")
        self._env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.root)})
        self._env.start()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self, message: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)

    def close(self) -> None:
        self._env.stop()
        self._tmp.cleanup()


def run_main(func, argv) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = func(argv)
    return code, out.getvalue()


class GlobTests(unittest.TestCase):
    def test_leading_double_star_matches_at_root(self):
        self.assertTrue(glob_match("test/a.py", "**/test/**"))
        self.assertTrue(glob_match("pkg/test/a.py", "**/test/**"))

    def test_dotted_directory_is_not_stripped(self):
        self.assertFalse(glob_match(".github/x.yml", "github/*"))

    def test_source_file_is_not_a_test(self):
        self.assertFalse(glob_match("src/latest.ts", "**/*.test.*"))


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo({"sources": {"tier1": ["docs.python.org"], "tier2": ["blog.example.com"]}})
        self.repo.write("src/lib.py", "def clamp_velocity(v):\n    return max(1, min(127, v))\n")

    def tearDown(self):
        self.repo.close()

    def check(self, body: str, *extra: str) -> tuple[int, str]:
        doc = self.repo.write("research.md", f"# R\n\n```citations\n{body}```\n")
        return run_main(check_citations.main, [str(doc), *extra])

    def test_local_quote_found_passes(self):
        code, out = self.check(
            "- id: C1\n  claim: Velocity is clamped.\n  source: file:src/lib.py\n  tier: 1\n"
            "  quote: return max(1, min(127, v))\n"
        )
        self.assertEqual(code, 0, out)
        self.assertIn("pass", out)

    def test_local_quote_missing_fails(self):
        code, out = self.check(
            "- id: C1\n  claim: Velocity is clamped.\n  source: file:src/lib.py\n  tier: 1\n"
            "  quote: return clamp(0, 255, value)\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("quote not found", out)

    def test_overclaimed_tier_fails(self):
        code, out = self.check(
            "- id: C1\n  claim: X.\n  source: https://blog.example.com/post\n  tier: 1\n"
            "  quote: some long enough quote text here\n  override: checked by hand\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("declared Tier 1", out)

    def test_unlisted_domain_must_be_pointer(self):
        code, out = self.check(
            "- id: C1\n  claim: X.\n  source: https://random.example.org/a\n  tier: 3\n"
            "  quote: some long enough quote text here\n  override: checked by hand\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("pointers", out)
        code, out = self.check(
            "- id: C1\n  claim: X.\n  source: https://random.example.org/a\n  tier: 3\n  role: pointer\n"
            "  quote: some long enough quote text here\n  override: checked by hand\n"
        )
        self.assertEqual(code, 0, out)
        self.assertIn("override", out)

    def test_unverified_is_allowed(self):
        code, out = self.check("- id: C1\n  claim: Live slices at transients.\n  status: unverified\n")
        self.assertEqual(code, 0, out)
        self.assertIn("unverified", out)

    def test_missing_fields_fail(self):
        code, out = self.check("- id: C1\n  claim: X.\n  source: file:src/lib.py\n")
        self.assertEqual(code, 1)
        self.assertIn("missing tier, quote", out)

    def test_require_fails_without_citations(self):
        doc = self.repo.write("empty.md", "# nothing\n")
        code, _ = run_main(check_citations.main, [str(doc), "--require"])
        self.assertEqual(code, 1)

    def test_normalize_folds_typography(self):
        self.assertEqual(check_citations.normalize("It\u2019s  \u201cfast\u201d \u2014 ok"), 'it\'s "fast" - ok')


class AcCoverageTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write(
            "docs/specs/arp/requirements.md",
            "- Status: approved\n\n- **AC-1** When x, the system shall y.\n"
            "- **AC-2** If z, then the system shall w.\n- **AC-3** (deferred) When q.\n",
        )

    def tearDown(self):
        self.repo.close()

    def test_missing_criterion_fails(self):
        self.repo.write("test/arp.test.ts", 'it("[arp AC-1] does y", () => {});\n')
        code, out = run_main(check_ac_coverage.main, ["arp"])
        self.assertEqual(code, 1)
        self.assertIn("MISSING    AC-2", out)
        self.assertIn("deferred   AC-3", out)

    def test_all_covered_passes(self):
        self.repo.write("test/arp.test.ts", 'it("[arp AC-1] y", f);\nit("[arp AC-2] w", f);\n')
        code, out = run_main(check_ac_coverage.main, ["arp"])
        self.assertEqual(code, 0, out)

    def test_tag_outside_test_files_does_not_count(self):
        self.repo.write("src/arp.ts", "// [arp AC-1] [arp AC-2]\n")
        code, _ = run_main(check_ac_coverage.main, ["arp"])
        self.assertEqual(code, 1)

    def test_unknown_criterion_fails(self):
        self.repo.write("test/arp.test.ts", 'it("[arp AC-1] y", f);\nit("[arp AC-2] w", f);\nit("[arp AC-9] ?", f);\n')
        code, out = run_main(check_ac_coverage.main, ["arp"])
        self.assertEqual(code, 1)
        self.assertIn("UNKNOWN    AC-9", out)

    def test_changed_since_checks_only_approved_changed_features(self):
        self.repo.commit("spec")
        git(self.repo.root, "branch", "base")
        self.repo.write("docs/specs/draft/requirements.md", "- Status: draft\n\n- **AC-1** When a.\n")
        self.repo.write("docs/specs/arp/design.md", "# d\n")
        self.repo.commit("change")
        code, out = run_main(check_ac_coverage.main, ["--changed-since", "base"])
        self.assertEqual(code, 1)
        self.assertIn("arp:", out)
        self.assertNotIn("draft:", out)


class WorkaroundTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("src/a.ts", "export const a = 1;\n")
        self.repo.write("test/a.test.ts", 'it("a", () => {});\n')
        self.repo.write("vitest.config.ts", "thresholds: { lines: 90 },\n")
        self.repo.commit("base")
        git(self.repo.root, "branch", "base")

    def tearDown(self):
        self.repo.close()

    def run_detect(self) -> tuple[int, str]:
        # Stage everything: the detector reads `git diff`, which skips untracked files.
        git(self.repo.root, "add", "-A")
        return run_main(detect_workarounds.main, ["--base", "base"])

    def test_clean_change_passes(self):
        self.repo.write("src/a.ts", "export const a = 2;\n")
        code, out = self.run_detect()
        self.assertEqual(code, 0, out)

    def test_each_workaround_is_flagged(self):
        self.repo.write("test/a.test.ts", 'it.skip("a", () => {});\n')
        self.repo.write(
            "src/a.ts", "// @ts-ignore\nexport const a = 1; // oxlint-disable-line\n/* istanbul ignore next */\n"
        )
        self.repo.write("vitest.config.ts", "thresholds: { lines: 80 },\n")
        code, out = self.run_detect()
        self.assertEqual(code, 1)
        for kind in ("test-skip", "type-suppression", "lint-suppression", "coverage-exclusion", "threshold-change"):
            self.assertIn(kind, out)

    def test_deleted_test_is_flagged(self):
        (self.repo.root / "test/a.test.ts").unlink()
        code, out = self.run_detect()
        self.assertEqual(code, 1)
        self.assertIn("deleted-test", out)

    def test_allow_marker_passes_with_reason(self):
        self.repo.write(
            "src/a.ts", "// @ts-ignore groundwork-allow: upstream types are wrong, see #12\nexport const a = 1;\n"
        )
        code, out = self.run_detect()
        self.assertEqual(code, 0, out)
        self.assertIn("upstream types are wrong", out)

    def test_lowered_fail_under_is_flagged(self):
        self.repo.write("pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
        code, out = self.run_detect()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"threshold-change\s+pyproject.toml")

    def test_multiline_threshold_block_is_flagged(self):
        self.repo.write("vitest.config.ts", "thresholds: {\n  lines: 90,\n},\n")
        self.repo.commit("multi-line thresholds")
        git(self.repo.root, "branch", "-f", "base")
        self.repo.write("vitest.config.ts", "thresholds: {\n  lines: 80,\n},\n")
        code, out = self.run_detect()
        self.assertEqual(code, 1)
        self.assertIn("threshold-change-metric", out)

    def test_documentation_is_not_scanned(self):
        self.repo.write("docs/guide.md", "Never add @ts-ignore or lower the coverage threshold: 80.\n")
        code, out = self.run_detect()
        self.assertEqual(code, 0, out)

    def test_word_skip_in_prose_is_not_flagged(self):
        self.repo.write(
            "src/a.ts", "// skip empty rows; only the first match counts above the threshold\nexport const a = 1;\n"
        )
        code, out = self.run_detect()
        self.assertEqual(code, 0, out)


class CommitGateTests(unittest.TestCase):
    """The gate runs `onCommit` before `git commit`; the check here is a marker-file test."""

    def setUp(self):
        # The check fails while `broken` exists, and counts its runs in `runs.log`.
        self.repo = Repo({"onCommit": "echo run >> runs.log && test ! -e broken"})
        self.repo.write(".gitignore", "runs.log\n.groundwork/state/\n")
        self.repo.write("src/a.py", "a = 1\n")
        self.repo.commit("base")
        self.config = load_config(self.repo.root)

    def tearDown(self):
        self.repo.close()

    def gate(self, command: str = "git add -A && git commit -m x") -> str | None:
        return hook_commit_gate.gate(command, self.repo.root, self.config)

    def runs(self) -> int:
        log = self.repo.root / "runs.log"
        return len(log.read_text().splitlines()) if log.exists() else 0

    def test_failing_check_blocks_commit(self):
        self.repo.write("src/a.py", "a = 2\n")
        self.repo.write("broken", "")
        reason = self.gate()
        self.assertIsNotNone(reason)
        self.assertIn("commit was not made", reason)

    def test_passing_check_allows_and_is_cached(self):
        self.repo.write("src/a.py", "a = 2\n")
        self.assertIsNone(self.gate())
        self.assertIsNone(self.gate())
        self.assertEqual(self.runs(), 1)
        self.repo.write("src/a.py", "a = 3\n")
        self.assertIsNone(self.gate())
        self.assertEqual(self.runs(), 2)

    def test_other_commands_do_not_run_checks(self):
        self.repo.write("src/a.py", "a = 2\n")
        self.repo.write("broken", "")
        for command in ("git status", "git log --grep commit", "echo git commit-tree", "pnpm test"):
            self.assertIsNone(self.gate(command), command)
        self.assertEqual(self.runs(), 0)

    def test_commit_with_global_options_is_gated(self):
        self.repo.write("src/a.py", "a = 2\n")
        self.repo.write("broken", "")
        self.assertIsNotNone(self.gate("git -C . commit -m x"))
        self.assertIsNotNone(self.gate("cd src; git -c user.name=x commit -am y"))

    def test_docs_only_change_skips_checks(self):
        self.repo.write("docs/notes.md", "text\n")
        self.repo.write("broken", "")
        self.repo.write(".gitignore", "runs.log\n.groundwork/state/\nbroken\n")
        self.repo.commit("ignore marker")
        self.repo.write("docs/notes.md", "more text\n")
        self.assertIsNone(self.gate())
        self.assertEqual(self.runs(), 0)

    def test_no_check_configured_allows(self):
        self.config["onCommit"] = None
        self.repo.write("src/a.py", "a = 2\n")
        self.repo.write("broken", "")
        self.assertIsNone(self.gate())


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.config = load_config(self.repo.root)
        self.lock = self.repo.write(".groundwork/state/tests-locked", "")

    def tearDown(self):
        self.repo.close()

    def decide(self, tool: str, **tool_input) -> str | None:
        return hook_guard_tests.decide({"tool_name": tool, "tool_input": tool_input}, self.repo.root, self.config)

    def test_edit_to_test_file_denied_when_locked(self):
        self.assertIsNotNone(self.decide("Edit", file_path=str(self.repo.root / "test/a.test.ts")))

    def test_edit_to_source_allowed(self):
        self.assertIsNone(self.decide("Edit", file_path=str(self.repo.root / "src/a.ts")))

    def test_nothing_denied_without_lock(self):
        self.lock.unlink()
        self.assertIsNone(self.decide("Write", file_path="test/a.test.ts"))

    def test_running_tests_with_stderr_redirect_allowed(self):
        self.assertIsNone(self.decide("Bash", command="pnpm vitest run test/a.test.ts 2>&1 | tail -5"))

    def test_shell_write_to_test_denied(self):
        self.assertIsNotNone(self.decide("Bash", command="echo 'x' > test/a.test.ts"))
        self.assertIsNotNone(self.decide("Bash", command="sed -i 's/a/b/' test/a.test.ts"))
        self.assertIsNotNone(self.decide("Bash", command="git checkout HEAD~1 -- test/a.test.ts"))

    def test_lock_removal_denied_but_creation_allowed(self):
        self.assertIsNotNone(self.decide("Bash", command="rm .groundwork/state/tests-locked"))
        self.assertIsNone(
            self.decide("Bash", command="mkdir -p .groundwork/state && touch .groundwork/state/tests-locked")
        )
        self.assertIsNone(self.decide("Bash", command="ls .groundwork/state 2>/dev/null"))


if __name__ == "__main__":
    unittest.main()
