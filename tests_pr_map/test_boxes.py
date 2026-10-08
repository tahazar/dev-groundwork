"""Which constructs the map shows, and with which status (AC-1 to AC-3, AC-8 to AC-10, AC-19)."""

from __future__ import annotations

import unittest

from helpers import MapRepo

PY_BASE = """\
def keep():
    return 1


def edit(x):
    return x + 1


def sign(a):
    return a


def drop():
    return 0


class Shape:
    sides = 3

    def area(self):
        return 0
"""


class BoxTests(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)

    def test_body_change_marks_function_changed(self):  # [pr-map AC-1]
        self.repo.base({"lib.py": PY_BASE})
        self.repo.head({"lib.py": PY_BASE.replace("return x + 1", "return x + 2")})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "edit"), "changed")
        self.assertIsNone(m.box("lib.py", "keep"), "an untouched function with no arrow to a change is not a box")

    def test_signature_change_marks_function_changed(self):  # [pr-map AC-1]
        self.repo.base({"lib.py": PY_BASE})
        self.repo.head({"lib.py": PY_BASE.replace("def sign(a):", "def sign(a, b=0):")})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "sign"), "changed")

    def test_change_inside_method_marks_only_the_method(self):  # [pr-map AC-1]
        self.repo.base({"lib.py": PY_BASE})
        self.repo.head({"lib.py": PY_BASE.replace("        return 0\n", "        return 1\n")})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "Shape.area"), "changed")
        self.assertNotEqual(m.status("lib.py", "Shape"), "changed", "the innermost construct owns the line")

    def test_class_level_change_marks_the_class(self):  # [pr-map AC-1]
        self.repo.base({"lib.py": PY_BASE})
        self.repo.head({"lib.py": PY_BASE.replace("sides = 3", "sides = 4")})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "Shape"), "changed")
        self.assertNotEqual(m.status("lib.py", "Shape.area"), "changed")

    def test_new_function_marked_added(self):  # [pr-map AC-2]
        self.repo.base({"lib.py": PY_BASE})
        self.repo.head({"lib.py": PY_BASE + "\n\ndef fresh():\n    return 2\n"})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "fresh"), "added")

    def test_new_typescript_method_marked_added(self):  # [pr-map AC-2]
        base = "export class Box {\n  open(): number {\n    return 1;\n  }\n}\n"
        self.repo.base({"src/box.ts": base})
        self.repo.head({"src/box.ts": base.replace("  }\n}", "  }\n  close(): number {\n    return 0;\n  }\n}")})
        m = self.repo.build()
        self.assertEqual(m.status("src/box.ts", "Box.close"), "added")

    def test_deleted_function_marked_removed(self):  # [pr-map AC-3]
        self.repo.base({"lib.py": PY_BASE})
        self.repo.head({"lib.py": PY_BASE.replace("def drop():\n    return 0\n\n\n", "")})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "drop"), "removed")

    def test_deleted_file_marks_its_functions_removed(self):  # [pr-map AC-3]
        self.repo.base({"lib.py": PY_BASE, "old.py": "def legacy():\n    return 1\n"})
        self.repo.head({"old.py": None})
        m = self.repo.build()
        self.assertEqual(m.status("old.py", "legacy"), "removed")

    def test_box_carries_name_and_path(self):  # [pr-map AC-8]
        self.repo.base({"pkg/lib.py": PY_BASE})
        self.repo.head({"pkg/lib.py": PY_BASE.replace("return x + 1", "return x + 2")})
        m = self.repo.build()
        box = m.box("pkg/lib.py", "edit")
        self.assertIsNotNone(box)
        self.assertEqual((box["name"], box["path"], box["line"]), ("edit", "pkg/lib.py", 5))

    def test_typescript_and_python_changes_in_one_pull_request(self):  # [pr-map AC-9]
        ts = "export function total(xs: number[]): number {\n  return xs.length;\n}\n"
        tsx = "export function View(): JSX.Element {\n  return <div>a</div>;\n}\n"
        self.repo.base({"lib.py": PY_BASE, "src/total.ts": ts, "src/view.tsx": tsx})
        self.repo.head(
            {
                "lib.py": PY_BASE.replace("return x + 1", "return x + 2"),
                "src/total.ts": ts.replace("xs.length", "xs.length + 1"),
                "src/view.tsx": tsx.replace("<div>a</div>", "<div>b</div>"),
            }
        )
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "edit"), "changed")
        self.assertEqual(m.status("src/total.ts", "total"), "changed")
        self.assertEqual(m.status("src/view.tsx", "View"), "changed")

    def test_documentation_only_change_says_nothing_to_map(self):  # [pr-map AC-10]
        self.repo.base({"lib.py": PY_BASE, "README.md": "# Title\n"})
        self.repo.head({"README.md": "# Title\n\nMore words.\n"})
        m = self.repo.build()
        self.assertEqual(m.data["boxes"], [])
        self.assertIn("No function-level changes to map", m.comment)

    def test_overload_signatures_and_implementation_are_one_box(self):  # [pr-map AC-1]
        base = (
            "export function ov(x: number): number;\n"
            "export function ov(x: string): string;\n"
            "export function ov(x: number | string): number | string {\n  return x;\n}\n"
        )
        self.repo.base({"src/ov.ts": base})
        self.repo.head({"src/ov.ts": base.replace("  return x;", "  return x ?? 0;")})
        m = self.repo.build()
        ov_boxes = [b for b in m.data["boxes"] if b["name"] == "ov"]
        self.assertEqual(len(ov_boxes), 1)
        self.assertEqual(ov_boxes[0]["status"], "changed")

    def test_repeated_names_in_one_file_are_separate_boxes(self):  # [pr-map AC-1]
        base = (
            "class Clip:\n"
            "    @property\n"
            "    def gain(self):\n        return self._g\n\n"
            "    @gain.setter\n"
            "    def gain(self, v):\n        self._g = v\n"
        )
        self.repo.base({"clip.py": base})
        self.repo.head({"clip.py": base.replace("self._g = v", "self._g = max(v, 0)")})
        m = self.repo.build()
        self.assertNotEqual(m.status("clip.py", "Clip.gain"), "changed", "the getter did not change")
        self.assertEqual(m.status("clip.py", "Clip.gain#2"), "changed", "the setter is the second `gain`")

    def test_syntax_error_file_is_mapped_from_the_parts_that_parse(self):  # [pr-map AC-19]
        base = "def good():\n    return 1\n\n\ndef other():\n    return 2\n"
        broken = "def good():\n    return 3\n\n\ndef other(:\n    return 2\n"
        self.repo.base({"lib.py": base})
        self.repo.head({"lib.py": broken})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "good"), "changed")
        self.assertIn("lib.py", m.comment)
        self.assertIn("syntax error", m.comment.lower())

    def test_unreadable_file_is_skipped_and_named(self):  # [pr-map AC-19]
        self.repo.base({"lib.py": PY_BASE})
        (self.repo.root / "bad.py").write_bytes(b"def f():\n    return '\xff\xfe'\n")
        self.repo.head({"lib.py": PY_BASE.replace("return x + 1", "return x + 2")})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "edit"), "changed")
        self.assertIn("bad.py", m.comment)
        self.assertIn("skipped", m.comment.lower())


if __name__ == "__main__":
    unittest.main()
