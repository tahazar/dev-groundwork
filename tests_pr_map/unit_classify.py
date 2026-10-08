"""Tests for classification in pr_map.py. Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import constructs
import pr_map
from helpers import MapRepo


def parse(path: str, text: str) -> constructs.FileConstructs:
    return constructs.parse(path, text.encode("utf-8"))


def statuses(boxes: list[pr_map.Box]) -> dict[str, str]:
    return {b.id: b.status for b in boxes}


class HunkTests(unittest.TestCase):
    def test_counts_give_deleted_and_added_ranges(self):
        self.assertEqual(pr_map.parse_hunks("@@ -3,2 +3,3 @@\n-a\n-b\n+a\n+b\n+c\n"), ({3, 4}, {3, 4, 5}))

    def test_header_without_counts_means_one_line(self):
        self.assertEqual(pr_map.parse_hunks("@@ -7 +7 @@ def f():\n-x\n+y\n"), ({7}, {7}))

    def test_pure_deletion_adds_no_head_line(self):
        self.assertEqual(pr_map.parse_hunks("@@ -5,2 +4,0 @@\n-a\n-b\n"), ({5, 6}, set()))

    def test_pure_addition_deletes_no_base_line(self):
        self.assertEqual(pr_map.parse_hunks("@@ -4,0 +5,2 @@\n+a\n+b\n"), (set(), {5, 6}))

    def test_several_hunks_and_file_headers(self):
        diff = "diff --git a/lib.py b/lib.py\n--- a/lib.py\n+++ b/lib.py\n@@ -1 +1 @@\n-a\n+b\n@@ -9,0 +10 @@\n+c\n"
        self.assertEqual(pr_map.parse_hunks(diff), ({1}, {1, 10}))

    def test_content_line_that_looks_like_a_header_is_ignored(self):
        self.assertEqual(pr_map.parse_hunks("@@ -1 +1 @@\n-@@ -50 +50 @@\n+x\n"), ({1}, {1}))


class NameStatusTests(unittest.TestCase):
    def test_statuses_and_rename_pairs(self):
        text = "M\0a.py\0A\0b.ts\0D\0c.tsx\0R087\0old.py\0new.py\0"
        self.assertEqual(
            pr_map.parse_name_status(text),
            [
                pr_map.FileChange("a.py", "a.py"),
                pr_map.FileChange(None, "b.ts"),
                pr_map.FileChange("c.tsx", None),
                pr_map.FileChange("old.py", "new.py"),
            ],
        )

    def test_other_languages_and_skipped_directories_are_left_out(self):
        text = "M\0README.md\0M\0node_modules/x/index.ts\0M\0src/dist.py\0"
        self.assertEqual(pr_map.parse_name_status(text), [pr_map.FileChange("src/dist.py", "src/dist.py")])

    def test_rename_to_another_language_removes_the_old_file(self):
        self.assertEqual(pr_map.parse_name_status("R090\0a.py\0a.txt\0"), [pr_map.FileChange("a.py", None)])

    def test_path_with_spaces_and_tab_is_kept_as_is(self):
        self.assertEqual(
            pr_map.parse_name_status("M\0my dir/a\tb.py\0"), [pr_map.FileChange("my dir/a\tb.py", "my dir/a\tb.py")]
        )


class OwnerTests(unittest.TestCase):
    SOURCE = (
        "class Shape:\n"  # 1
        "    sides = 3\n"  # 2
        "\n"  # 3
        "    @staticmethod\n"  # 4
        "    def area():\n"  # 5
        "        def unit():\n"  # 6
        "            return 1\n"  # 7
        "        return unit()\n"  # 8
        "\n"  # 9
        "\n"  # 10
        "x = 1\n"  # 11
    )

    def owners(self, lines: set[int]) -> set[str]:
        return pr_map.owners(parse("lib.py", self.SOURCE).constructs, lines)

    def test_line_belongs_to_its_innermost_construct(self):
        self.assertEqual(self.owners({7}), {"lib.py::Shape.area.unit"})
        self.assertEqual(self.owners({8}), {"lib.py::Shape.area"})
        self.assertEqual(self.owners({2}), {"lib.py::Shape"})

    def test_decorator_line_belongs_to_the_decorated_method(self):
        self.assertEqual(self.owners({4}), {"lib.py::Shape.area"})

    def test_module_level_line_has_no_owner(self):
        self.assertEqual(self.owners({11}), set())


class ClassifyTests(unittest.TestCase):
    def test_signature_change_marks_the_function_changed(self):
        before = parse("lib.py", "def f(a):\n    return a\n")
        after = parse("lib.py", "def f(a, b):\n    return a\n")
        self.assertEqual(statuses(pr_map.classify(before, after, {1}, {1})), {"lib.py::f": "changed"})

    def test_pure_deletion_inside_a_function_changes_it(self):
        before = parse("lib.py", "def f():\n    x = 1\n    return 2\n")
        after = parse("lib.py", "def f():\n    return 2\n")
        self.assertEqual(statuses(pr_map.classify(before, after, {2}, set())), {"lib.py::f": "changed"})

    def test_change_in_a_method_does_not_change_its_class(self):
        before = parse("lib.py", "class C:\n    def m(self):\n        return 1\n")
        after = parse("lib.py", "class C:\n    def m(self):\n        return 2\n")
        self.assertEqual(statuses(pr_map.classify(before, after, {3}, {3})), {"lib.py::C.m": "changed"})

    def test_added_and_removed(self):
        before = parse("lib.py", "def old():\n    return 1\n")
        after = parse("lib.py", "def new():\n    return 1\n")
        self.assertEqual(
            statuses(pr_map.classify(before, after, {1}, {1})), {"lib.py::new": "added", "lib.py::old": "removed"}
        )

    def test_new_and_deleted_files(self):
        file = parse("lib.py", "def f():\n    return 1\n")
        self.assertEqual(statuses(pr_map.classify(None, file, set(), set())), {"lib.py::f": "added"})
        self.assertEqual(statuses(pr_map.classify(file, None, set(), set())), {"lib.py::f": "removed"})

    def test_repeated_names_pair_by_ordinal(self):
        text = "if X:\n    def f():\n        return 1\nelse:\n    def f():\n        return 2\n"
        before = parse("lib.py", text)
        after = parse("lib.py", text.replace("return 2", "return 3"))
        self.assertEqual(statuses(pr_map.classify(before, after, {6}, {6})), {"lib.py::f#2": "changed"})

    def test_renamed_file_pairs_constructs_across_paths(self):
        before = parse("old.py", "def f():\n    return 1\n\n\ndef g():\n    return 1\n")
        after = parse("new.py", "def f():\n    return 2\n\n\ndef g():\n    return 1\n")
        self.assertEqual(statuses(pr_map.classify(before, after, {2}, {2})), {"new.py::f": "changed"})

    def test_box_takes_the_head_position_and_the_base_one_when_removed(self):
        before = parse("lib.py", "def gone():\n    return 1\n\n\ndef f():\n    return 1\n")
        after = parse("lib.py", "def f():\n    return 2\n")
        boxes = {b.id: b for b in pr_map.classify(before, after, {1, 2, 3, 4, 6}, {2})}
        self.assertEqual((boxes["lib.py::f"].line, boxes["lib.py::f"].status), (1, "changed"))
        self.assertEqual((boxes["lib.py::gone"].line, boxes["lib.py::gone"].status), (1, "removed"))


class BuildMapTests(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)

    def test_renamed_and_edited_file_changes_only_the_edited_function(self):
        body = "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(8))
        self.repo.base({"old.py": body})
        (self.repo.root / "old.py").unlink()
        self.repo.head({"new.py": body.replace("return 3", "return 33")})
        data = pr_map.build_map(self.repo.root, "base")
        self.assertEqual([(b["id"], b["status"]) for b in data["boxes"]], [("new.py::f3", "changed")])

    def test_records_base_and_head_commits(self):
        self.repo.base({"lib.py": "def f():\n    return 1\n"})
        self.repo.head({"lib.py": "def f():\n    return 2\n"})
        data = pr_map.build_map(self.repo.root, "base")
        self.assertEqual(len(data["base"]), 40)
        self.assertEqual(len(data["head"]), 40)
        self.assertNotEqual(data["base"], data["head"])

    def test_unreadable_file_is_noted_and_the_rest_mapped(self):
        self.repo.base({"lib.py": "def f():\n    return 1\n"})
        (self.repo.root / "bad.py").write_bytes(b"def g():\n    return '\xff'\n")
        self.repo.head({"lib.py": "def f():\n    return 2\n"})
        data = pr_map.build_map(self.repo.root, "base")
        self.assertEqual([b["id"] for b in data["boxes"]], ["lib.py::f"])
        [skipped] = data["notes"]["skipped"]
        self.assertEqual(skipped["path"], "bad.py")
        self.assertIn("not UTF-8", skipped["reason"])

    def test_unreadable_base_version_skips_the_whole_file(self):
        self.repo.base({"lib.py": "def f():\n    return 1\n"})
        (self.repo.root / "lib.py").write_bytes(b"def f():\n    return '\xff'\n")
        self.repo.commit("base, not UTF-8")
        self.repo.head({"lib.py": "def f():\n    return 2\n"})
        data = pr_map.build_map(self.repo.root, "HEAD~1")
        self.assertEqual(data["boxes"], [], "half a pair would show every construct as added")
        [skipped] = data["notes"]["skipped"]
        self.assertEqual(skipped["path"], "lib.py")
        self.assertTrue(skipped["reason"].startswith("base version: lib.py is not UTF-8"), skipped["reason"])

    def test_syntax_errors_are_noted_with_their_lines(self):
        self.repo.base({"lib.py": "def good():\n    return 1\n"})
        self.repo.head({"lib.py": "def good():\n    return 3\n\n\ndef other(:\n    return 2\n"})
        data = pr_map.build_map(self.repo.root, "base")
        self.assertIn("lib.py::good", [b["id"] for b in data["boxes"]])
        [error] = data["notes"]["syntax_errors"]
        self.assertEqual(error["path"], "lib.py")
        self.assertIn(5, error["lines"])

    def test_clean_change_has_no_notes(self):
        self.repo.base({"lib.py": "def f():\n    return 1\n"})
        self.repo.head({"lib.py": "def f():\n    return 2\n"})
        self.assertEqual(pr_map.build_map(self.repo.root, "base")["notes"], {})

    def test_unknown_base_names_the_step_and_keeps_the_cause(self):
        self.repo.base({"lib.py": "def f():\n    return 1\n"})
        with self.assertRaises(pr_map.MapError) as raised:
            pr_map.build_map(self.repo.root, "no-such-ref")
        self.assertIn("finding the merge base of no-such-ref", str(raised.exception))
        self.assertIsNotNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
