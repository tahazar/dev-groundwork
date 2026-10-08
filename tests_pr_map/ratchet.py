#!/usr/bin/env python3
"""Run the pr-map acceptance tests and fail only if a test listed in passing.txt fails.

Usage:
    ratchet.py [--start DIR] [--passing FILE]

Every acceptance test fails until pr-map is complete, so CI cannot require
them all. passing.txt lists the tests that already pass, one unittest id per
line (blank lines and lines starting with # are ignored). This runner runs
the whole suite, prints how many tests pass, and exits 1 if a listed test
fails, a listed id names no test, or a test module cannot be loaded. Tests
that fail and are not listed do not fail the run; tests that pass and are
not listed are printed so they can be added.
"""

from __future__ import annotations

import argparse
import io
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_passing(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read the passing list {path}: {exc}") from exc
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def collect_ids(suite: unittest.TestSuite) -> list[str]:
    ids = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            ids += collect_ids(item)
        else:
            ids.append(item.id())
    return ids


def case_id(test: unittest.TestCase) -> str:
    """Id of the test method, also for a failed subTest (which carries its parent as test_case)."""
    return getattr(test, "test_case", test).id()


def not_passing(result: unittest.TestResult) -> set[str]:
    bad = result.failures + result.errors + result.skipped
    return {case_id(test) for test, _ in bad} | {case_id(test) for test in result.unexpectedSuccesses}


def run(start: Path, passing_file: Path) -> int:
    listed = read_passing(passing_file)
    loader = unittest.TestLoader()
    suite = loader.discover(str(start), top_level_dir=str(start))
    if loader.errors:
        print("cannot load the acceptance tests:", file=sys.stderr)
        for error in loader.errors:
            print(error, file=sys.stderr)
        return 1

    ids = collect_ids(suite)
    unknown = sorted(set(listed) - set(ids))
    if unknown:
        print(f"{passing_file.name} lists ids that name no test:", file=sys.stderr)
        for name in unknown:
            print(f"  {name}", file=sys.stderr)
        return 1

    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    bad = not_passing(result)
    passing = [name for name in ids if name not in bad]
    print(f"{len(set(passing))} of {len(set(ids))} acceptance tests pass ({len(set(listed))} required)")

    newly = sorted(set(passing) - set(listed))
    if newly:
        print(f"passing but not in {passing_file.name} yet (add them):")
        for name in newly:
            print(f"  {name}")

    regressed = sorted(set(listed) & bad)
    if regressed:
        print(f"\n{len(regressed)} test(s) listed in {passing_file.name} do not pass:", file=sys.stderr)
        for test, trace in result.failures + result.errors:
            if case_id(test) in regressed:
                print(f"\n=== {test.id()}\n{trace}", file=sys.stderr)
        for test, reason in result.skipped:
            if case_id(test) in regressed:
                print(f"\n=== {test.id()} skipped: {reason}", file=sys.stderr)
        for test in result.unexpectedSuccesses:
            if case_id(test) in regressed:
                print(f"\n=== {test.id()} passed but is marked expectedFailure", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=Path, default=HERE, help="directory of test_*.py files (default: this one)")
    parser.add_argument("--passing", type=Path, help="the passing list (default: passing.txt in --start)")
    args = parser.parse_args(argv)
    return run(args.start.resolve(), args.passing or args.start / "passing.txt")


if __name__ == "__main__":
    raise SystemExit(main())
