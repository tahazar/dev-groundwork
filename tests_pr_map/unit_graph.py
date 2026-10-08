"""Tests for graph assembly in pr_map.py: candidates, aliases, import lines, module boxes and notes.

Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import constructs
import pr_map
import resolve
from helpers import MapRepo

TSCONFIG = json.dumps({"compilerOptions": {"strict": True, "module": "NodeNext"}, "include": ["src"]})


class Built:
    """build_map's result for a MapRepo, with lookups by source and target."""

    def __init__(self, data: dict):
        self.data = data
        self.boxes = {b["id"]: b for b in data["boxes"]}

    def arrows(self, source: str | None = None, target: str | None = None) -> list[dict]:
        return [
            a
            for a in self.data["arrows"]
            if (source is None or a["source"] == source) and (target is None or a["target"] == target)
        ]


class GraphCase(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)

    def build(self, base: dict[str, str], head: dict[str, str | None], **kw) -> Built:
        self.repo.base(base)
        self.repo.head(head)
        return Built(pr_map.build_map(self.repo.root, "base", **kw))


class CandidateTests(GraphCase):
    def test_callers_from_other_files_and_callees_one_step(self):
        lib = "def leaf():\n    return 1\n\n\ndef target():\n    return leaf()\n"
        use = "from lib import target\n\n\ndef caller():\n    return target()\n"
        m = self.build({"lib.py": lib, "use.py": use}, {"lib.py": lib.replace("leaf()\n", "leaf() + 1\n")})
        self.assertEqual(len(m.arrows("use.py::caller", "lib.py::target")), 1)
        self.assertEqual(m.arrows("lib.py::target", "lib.py::leaf")[0]["at"], "lib.py:6:11")
        self.assertEqual(m.boxes["use.py::caller"]["status"], "neighbour")
        self.assertEqual(m.boxes["lib.py::leaf"]["status"], "neighbour")
        self.assertEqual(m.data["notes"], {})

    def test_top_level_caller_gets_a_module_box(self):
        lib = "def target():\n    return 1\n"
        use = "from lib import target\n\ntarget()\n"
        m = self.build({"lib.py": lib, "use.py": use}, {"lib.py": lib.replace("1", "2")})
        [arrow] = m.arrows(target="lib.py::target")
        self.assertEqual(
            (arrow["source"], arrow["certainty"], arrow["at"]), ("use.py::<module>", "exact", "use.py:3:0")
        )
        module = m.boxes["use.py::<module>"]
        self.assertEqual((module["kind"], module["name"], module["status"]), ("module", "use.py", "neighbour"))

    def test_nested_function_owns_its_own_calls(self):
        lib = (
            "def leaf():\n    return 1\n\n\n"
            "def outer():\n    x = 1\n\n    def inner():\n        return leaf()\n\n    return inner\n"
        )
        m = self.build({"lib.py": lib}, {"lib.py": lib.replace("x = 1", "x = 2")})
        self.assertEqual(m.boxes["lib.py::outer"]["status"], "changed")
        self.assertEqual(m.arrows("lib.py::outer", "lib.py::leaf"), [], "leaf() is inner's call, not outer's")
        self.assertEqual(len(m.arrows("lib.py::outer", "lib.py::outer.inner")), 1, "outer refers to inner")

    def test_unresolved_callee_lists_its_possible_targets_instead_of_fanning_out(self):
        lib = (
            "class A:\n    def get(self):\n        return 1\n\n\n"
            "class B:\n    def get(self):\n        return 2\n\n\n"
            "def read(d):\n    return d.get()\n"
        )
        m = self.build({"lib.py": lib}, {"lib.py": lib.replace("return d.get()", "return d.get() or 0")})
        self.assertEqual(m.arrows("lib.py::read"), [])
        [entry] = m.data["notes"]["unresolved"]
        self.assertEqual(entry["at"], "lib.py:12:13")
        self.assertEqual(sorted(entry["options"]), ["lib.py::A.get", "lib.py::B.get"])

    def test_library_calls_are_counted_once_per_site(self):
        lib = "def mean(xs):\n    return xs\n\n\ndef array(xs):\n    return xs\n"
        use = "import numpy as np\n\n\ndef stats(xs):\n    return np.mean(np.array(xs))\n"
        head = {"lib.py": lib.replace("return xs", "return list(xs)")}
        m = self.build({"lib.py": lib, "use.py": use}, head)
        self.assertEqual(m.arrows(source="use.py::stats"), [])
        self.assertEqual(m.data["notes"]["library_calls"], [{"path": "use.py", "count": 2}])

    def test_cls_call_outside_the_constructors_runners_is_no_candidate(self):
        lib = (
            "class Foo:\n    def __init__(self, n):\n        self.n = n\n\n"
            "    @classmethod\n    def make(cls):\n        return cls(0)\n\n\n"
            "class Other:\n    @classmethod\n    def make(cls):\n        return cls()\n"
        )
        m = self.build({"lib.py": lib}, {"lib.py": lib.replace("self.n = n", "self.n = int(n)")})
        init = "lib.py::Foo.__init__"
        [arrow] = m.arrows(target=init)
        self.assertEqual(
            (arrow["source"], arrow["certainty"], arrow["reason"]), ("lib.py::Foo.make", "possible", "through `cls`")
        )


class ImportLineTests(GraphCase):
    def test_import_lines_draw_no_arrows_and_add_no_boxes(self):
        lib = "def target():\n    return 1\n"
        unused = "from lib import target\n"
        m = self.build({"lib.py": lib, "unused.py": unused}, {"lib.py": lib.replace("1", "2")})
        self.assertEqual(m.data["arrows"], [])
        self.assertEqual(list(m.boxes), ["lib.py::target"])

    def test_alias_uses_in_the_importing_file_are_candidates(self):
        report = "def save_record(p):\n    return p\n"
        use = (
            "from report import save_record as save\n\n\n"
            "def a():\n    return save(1)\n\n\ndef b():\n    return save(2)\n"
        )
        other = "def save():\n    return 0\n\n\ndef c():\n    return save()\n"
        files = {"report.py": report, "use.py": use, "other.py": other}
        m = self.build(files, {"report.py": report.replace("return p", "return str(p)")})
        target = "report.py::save_record"
        self.assertEqual(sorted(a["source"] for a in m.arrows(target=target)), ["use.py::a", "use.py::b"])
        self.assertTrue(all(a["certainty"] == "exact" for a in m.arrows(target=target)))
        self.assertEqual(m.arrows(source="other.py::c"), [], "another file's `save` is not the alias")


class RemovedTests(GraphCase):
    def test_removed_box_callers_come_from_names_and_aliases_in_head(self):
        lib = "def gone():\n    return 1\n\n\ndef stay():\n    return 2\n"
        use = "from lib import gone as g\n\n\ndef caller():\n    return g()\n"
        m = self.build({"lib.py": lib, "use.py": use}, {"lib.py": "def stay():\n    return 2\n"})
        [arrow] = m.arrows(target="lib.py::gone")
        self.assertEqual(
            (arrow["source"], arrow["certainty"], arrow["reason"]), ("use.py::caller", "possible", "unresolved")
        )


class ClassBasesFallbackTests(unittest.TestCase):
    """The class-bases fallback (pr_map._class_bases), in both directions."""

    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)
        self.repo.base({"lib.py": "class Base:\n    pass\n\n\nclass Sub(Base):\n    pass\n"})
        self.files, _ = constructs.scan(self.repo.root)
        self.by_id, self.positions = resolve.index(self.files.values())

    def test_resolved_bases_are_class_ids(self):
        failures: list[dict] = []
        with self.assertNoLogs("pr_map", "WARNING"):
            bases = pr_map._class_bases(
                self.repo.root, self.by_id["lib.py::Sub"], self.positions, resolve.Resolver(self.repo.root), failures
            )
        self.assertEqual(bases, ("lib.py::Base",))
        self.assertEqual(failures, [])

    def test_a_resolver_failure_keeps_the_names_as_written(self):
        class Failing(resolve.Resolver):
            def definition_at(self, path, line, column):
                raise resolve.ResolverError(f"jedi goto at {path}:{line}:{column}: broken")

        failures: list[dict] = []
        with self.assertLogs("pr_map", "WARNING") as logged:
            bases = pr_map._class_bases(
                self.repo.root, self.by_id["lib.py::Sub"], self.positions, Failing(self.repo.root), failures
            )
        self.assertEqual(bases, ("Base",))
        self.assertIn("using their names as written", logged.output[0])
        self.assertEqual(failures, [{"at": "lib.py:5:6", "reason": "jedi goto at lib.py:5:10: broken"}])


class TypeScriptFallbackTests(GraphCase):
    """The TypeScript fallback seen from the map, in both directions."""

    LIB = (
        "export function target(): number {\n  return 1;\n}\n"
        "export function caller(): number {\n  return target();\n}\n"
    )

    def test_working_helper_draws_an_exact_arrow_and_no_fallback_note(self):
        m = self.build(
            {"tsconfig.json": TSCONFIG, "src/lib.ts": self.LIB}, {"src/lib.ts": self.LIB.replace("1;", "2;")}
        )
        [arrow] = m.arrows("src/lib.ts::caller", "src/lib.ts::target")
        self.assertEqual(arrow["certainty"], "exact")
        self.assertNotIn("typescript_fallback", m.data["notes"])

    def test_missing_node_gives_possible_arrows_and_says_why(self):
        base = {"tsconfig.json": TSCONFIG, "src/lib.ts": self.LIB}
        with self.assertLogs("pr_map", "WARNING"):
            m = self.build(base, {"src/lib.ts": self.LIB.replace("1;", "2;")}, node="/no/such/node")
        [arrow] = m.arrows("src/lib.ts::caller", "src/lib.ts::target")
        self.assertEqual(arrow["certainty"], "possible")
        self.assertRegex(
            arrow["reason"], "^resolver failed: TypeScript resolver unavailable: Node could not be started"
        )
        self.assertRegex(m.data["notes"]["typescript_fallback"], "Node could not be started")
        self.assertTrue(m.data["notes"]["resolver_failures"], "the reference search failed too, and is listed")


if __name__ == "__main__":
    unittest.main()
