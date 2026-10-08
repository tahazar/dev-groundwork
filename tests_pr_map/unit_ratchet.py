"""Tests for ratchet.py. Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RATCHET = Path(__file__).resolve().parent / "ratchet.py"

FAKE_SUITE = textwrap.dedent(
    """
    import unittest

    class Fake(unittest.TestCase):
        def test_good(self):
            pass

        def test_bad(self):
            self.fail("bad on purpose")

        def test_bad_subtest(self):
            with self.subTest(n=1):
                self.fail("bad subtest on purpose")

        @unittest.skip("skipped on purpose")  # groundwork-allow: proves a listed skip fails the ratchet
        def test_skipped(self):
            pass
    """
)

SETUP_FAILS = textwrap.dedent(
    """
    import unittest

    class Setup(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            raise RuntimeError("setup fails on purpose")

        def test_never_runs(self):
            pass
    """
)

EXPECTED_FAILURE = textwrap.dedent(
    """
    import unittest

    class Expected(unittest.TestCase):
        @unittest.expectedFailure
        def test_known_bad(self):
            self.fail("known bad")
    """
)


class RatchetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "test_fake.py").write_text(FAKE_SUITE, encoding="utf-8")

    def ratchet(self, *listed: str) -> subprocess.CompletedProcess:
        (self.dir / "passing.txt").write_text("# header\n\n" + "\n".join(listed) + "\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(RATCHET), "--start", str(self.dir)], capture_output=True, text=True, check=False
        )

    def test_empty_list_passes_and_counts(self):
        proc = self.ratchet()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1 of 4 acceptance tests pass (0 required)", proc.stdout)
        self.assertIn("test_fake.Fake.test_good", proc.stdout)

    def test_listed_passing_test_passes(self):
        proc = self.ratchet("test_fake.Fake.test_good")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1 of 4 acceptance tests pass (1 required)", proc.stdout)

    def test_unlisted_failing_test_does_not_fail_the_run(self):
        proc = self.ratchet("test_fake.Fake.test_good")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("bad on purpose", proc.stderr)

    def test_listed_failing_test_fails_the_run(self):
        proc = self.ratchet("test_fake.Fake.test_good", "test_fake.Fake.test_bad")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("1 test(s) listed in passing.txt do not pass", proc.stderr)
        self.assertIn("bad on purpose", proc.stderr)

    def test_listed_failing_subtest_fails_the_run(self):
        proc = self.ratchet("test_fake.Fake.test_bad_subtest")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("bad subtest on purpose", proc.stderr)

    def test_listed_skipped_test_fails_the_run(self):
        proc = self.ratchet("test_fake.Fake.test_skipped")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("skipped: skipped on purpose", proc.stderr)

    def test_listed_test_of_a_class_whose_setup_fails_fails_the_run(self):
        (self.dir / "test_setup.py").write_text(SETUP_FAILS, encoding="utf-8")
        proc = self.ratchet("test_setup.Setup.test_never_runs")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("1 of 5 acceptance tests pass", proc.stdout)
        self.assertIn("setup fails on purpose", proc.stderr)

    def test_listed_expected_failure_fails_the_run(self):
        (self.dir / "test_expected.py").write_text(EXPECTED_FAILURE, encoding="utf-8")
        proc = self.ratchet("test_expected.Expected.test_known_bad")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("test_expected.Expected.test_known_bad did not succeed", proc.stderr)

    def test_listed_id_naming_no_test_fails_the_run(self):
        proc = self.ratchet("test_fake.Fake.test_good", "test_fake.Fake.test_gone")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("lists ids that name no test", proc.stderr)
        self.assertIn("test_fake.Fake.test_gone", proc.stderr)

    def test_unloadable_module_fails_the_run(self):
        (self.dir / "test_broken.py").write_text("import no_such_module_for_ratchet\n", encoding="utf-8")
        proc = self.ratchet()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cannot load the acceptance tests", proc.stderr)
        self.assertIn("no_such_module_for_ratchet", proc.stderr)

    def test_missing_passing_list_fails_the_run(self):
        proc = subprocess.run(
            [sys.executable, str(RATCHET), "--start", str(self.dir)], capture_output=True, text=True, check=False
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cannot read the passing list", proc.stderr)


if __name__ == "__main__":
    unittest.main()
