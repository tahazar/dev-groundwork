"""Arrows in Python code (AC-3 to AC-7, AC-11).

Each fixture's `references` lists every reference site by hand with what it
really refers to; check_against holds every arrow on the map to that list.
"""

from __future__ import annotations

import unittest

from helpers import UNCERTAIN, MapRepo, box_id


class PythonArrowTests(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)

    def test_callers_and_callees_one_step_each_way(self):  # [pr-map AC-4] [pr-map AC-5]
        lib = "def leaf():\n    return 1\n\n\ndef target():\n    return leaf()\n\n\ndef far():\n    return 2\n"
        use = "from lib import target\n\n\ndef caller():\n    return target()\n\n\ndef outer():\n    return caller()\n"
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": lib.replace("return leaf()", "return leaf() + 1")})
        m = self.repo.build()
        target = box_id("lib.py", "target")
        self.assertEqual(m.certainty(box_id("use.py", "caller"), target), "exact")
        self.assertEqual(m.certainty(target, box_id("lib.py", "leaf")), "exact")
        self.assertIsNone(m.box("use.py", "outer"), "two steps away is out of scope")
        m.check_against(
            self,
            {
                self.repo.site("use.py", "return target()"): target,
                self.repo.site("lib.py", "return leaf()"): box_id("lib.py", "leaf"),
                self.repo.site("use.py", "from lib import target"): target,
            },
        )

    def test_same_named_functions_are_told_apart(self):  # [pr-map AC-5] [pr-map AC-7]
        report = "def save_record(path):\n    return path\n"
        drum = "def save_record(path):\n    return path\n"
        main = (
            "import drumstats\nimport report as report_mod\n\n\n"
            "def a():\n    return report_mod.save_record(1)\n\n\n"
            "def b():\n    return drumstats.save_record(2)\n"
        )
        self.repo.base({"report.py": report, "drumstats.py": drum, "main.py": main})
        self.repo.head({"report.py": report.replace("return path", "return str(path)")})
        m = self.repo.build()
        target = box_id("report.py", "save_record")
        self.assertEqual(m.certainty(box_id("main.py", "a"), target), "exact")
        self.assertIsNone(m.arrow(box_id("main.py", "b"), target), "b calls the drumstats function")
        m.check_against(
            self,
            {
                self.repo.site("main.py", "report_mod.save_record"): target,
                self.repo.site("main.py", "drumstats.save_record"): box_id("drumstats.py", "save_record"),
            },
        )

    def test_call_through_a_renamed_import(self):  # [pr-map AC-4] [pr-map AC-5]
        report = "def save_record(path):\n    return path\n"
        use = "from report import save_record as save\n\n\ndef caller():\n    return save(1)\n"
        self.repo.base({"report.py": report, "use.py": use})
        self.repo.head({"report.py": report.replace("return path", "return str(path)")})
        m = self.repo.build()
        arrow = m.arrow(box_id("use.py", "caller"), box_id("report.py", "save_record"))
        self.assertIsNotNone(arrow, "jedi alone misses calls through `as save`; pr-map follows the alias")
        self.assertEqual(arrow["certainty"], "exact")

    def test_function_passed_as_a_value(self):  # [pr-map AC-4]
        lib = "def handler(x):\n    return x\n\n\ndef register(callback):\n    return callback\n"
        use = "from lib import handler, register\n\n\ndef wire():\n    return register(callback=handler)\n"
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": lib.replace("return x\n", "return x * 2\n", 1)})
        m = self.repo.build()
        self.assertEqual(m.certainty(box_id("use.py", "wire"), box_id("lib.py", "handler")), "exact")

    def test_call_through_a_base_class_two_levels_up_is_possible(self):  # [pr-map AC-6]
        lib = (
            "class Base:\n    def run(self):\n        return 0\n\n\n"
            "class Mid(Base):\n    pass\n\n\n"
            "class Impl(Mid):\n    def run(self):\n        return 1\n\n\n"
            "def go(b: Base):\n    return b.run()\n"
        )
        self.repo.base({"lib.py": lib})
        self.repo.head({"lib.py": lib.replace("        return 1\n", "        return 2\n")})
        m = self.repo.build()
        arrow = m.arrow(box_id("lib.py", "go"), box_id("lib.py", "Impl.run"))
        self.assertIsNotNone(arrow, "b.run() may run Impl.run")
        self.assertEqual(arrow["certainty"], "possible")
        self.assertIn("Base.run", arrow["reason"])

    def test_call_through_a_protocol_is_possible(self):  # [pr-map AC-6]
        lib = (
            "from typing import Protocol\n\n\n"
            "class Runner(Protocol):\n    def run(self) -> int: ...\n\n\n"
            "class Job:\n    def run(self) -> int:\n        return 1\n\n\n"
            "def go(r: Runner) -> int:\n    return r.run()\n"
        )
        self.repo.base({"lib.py": lib})
        self.repo.head({"lib.py": lib.replace("        return 1\n", "        return 2\n")})
        m = self.repo.build()
        self.assertEqual(m.certainty(box_id("lib.py", "go"), box_id("lib.py", "Job.run")), "possible")

    def test_untyped_parameter_passed_two_classes_is_possible_not_exact(self):  # [pr-map AC-6]
        lib = (
            "class A:\n    def save(self):\n        return 1\n\n\n"
            "class B:\n    def save(self):\n        return 2\n\n\n"
            "def store(obj):\n    return obj.save()\n\n\nstore(A())\n"
        )
        other = "from lib import B, store\n\nstore(B())\n"
        self.repo.base({"lib.py": lib, "other.py": other})
        self.repo.head({"lib.py": lib.replace("        return 2\n", "        return 3\n")})
        m = self.repo.build()
        arrow = m.arrow(box_id("lib.py", "store"), box_id("lib.py", "B.save"))
        self.assertIsNotNone(arrow, "store may call B.save; inferring A from one call must not drop it")
        self.assertEqual(arrow["certainty"], "possible")

    def test_parameter_on_the_name_line_is_not_the_function(self):  # [pr-map AC-5] [pr-map AC-7]
        lib = "def apply(fn):\n    return fn()\n\n\ndef call_it():\n    return apply(lambda: 1)\n"
        self.repo.base({"lib.py": lib})
        self.repo.head({"lib.py": lib.replace("return fn()", "return fn() or 0")})
        m = self.repo.build()
        target = box_id("lib.py", "apply")
        self.assertEqual(m.certainty(box_id("lib.py", "call_it"), target), "exact", "positive control")
        self.assertIsNone(m.arrow(target, target), "fn() calls the parameter, not apply")

    def test_local_variable_with_a_box_name_draws_no_arrow(self):  # [pr-map AC-7]
        lib = "def handler():\n    return 1\n\n\ndef make():\n    return lambda: 2\n"
        use = (
            "from lib import handler, make\n\n\n"
            "def run():\n    handler = make()\n    return handler()\n\n\n"
            "def real():\n    return handler()\n"
        )
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": lib.replace("return 1", "return 3")})
        m = self.repo.build()
        target = box_id("lib.py", "handler")
        self.assertEqual(m.certainty(box_id("use.py", "real"), target), "exact", "positive control")
        self.assertIsNone(m.arrow(box_id("use.py", "run"), target), "run calls its local variable")

    def test_library_call_draws_no_arrow_to_a_same_named_function(self):  # [pr-map AC-7] [pr-map AC-11]
        lib = "def mean(xs):\n    return sum(xs) / len(xs)\n"
        use = "import numpy as np\n\n\ndef stats(xs):\n    arr = np.array(xs)\n    return np.mean(xs), arr.mean()\n"
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": lib.replace("len(xs)", "max(len(xs), 1)")})
        m = self.repo.build()
        self.assertIsNone(m.arrow(box_id("use.py", "stats"), box_id("lib.py", "mean")))
        self.assertIn("library call", m.comment.lower(), "library calls are counted, not silently dropped")

    def test_attribute_holding_a_function_draws_no_arrow_and_is_listed(self):  # [pr-map AC-7] [pr-map AC-11]
        lib = (
            "def notes():\n    return []\n\n\n"
            "class Clip:\n    def __init__(self):\n        self.notes = [1]\n\n"
            "    def count(self):\n        return len(self.notes)\n\n\n"
            "def fresh():\n    return notes()\n"
        )
        self.repo.base({"lib.py": lib})
        self.repo.head({"lib.py": lib.replace("return []", "return [0]")})
        m = self.repo.build()
        target = box_id("lib.py", "notes")
        self.assertEqual(m.certainty(box_id("lib.py", "fresh"), target), "exact", "positive control")
        self.assertIsNone(m.arrow(box_id("lib.py", "Clip.count"), target), "self.notes is the attribute")
        self.assertIn(self.repo.site("lib.py", "return len(self.notes)"), m.comment, "listed as a non-box reference")

    def test_constructor_callers(self):  # [pr-map AC-4] [pr-map AC-5] [pr-map AC-7]
        lib = (
            "class Foo:\n"
            "    def __init__(self, n):\n        self.n = n\n\n"
            "    @classmethod\n    def make(cls):\n        return cls(0)\n\n\n"
            "class Baz(Foo):\n    pass\n\n\n"
            "class Qux(Foo):\n    def __init__(self):\n        super().__init__(2)\n\n\n"
            "class Mixin:\n    def __init__(self, n):\n        self.m = n\n\n\n"
            "class Bad(Mixin, Foo):\n    pass\n"
        )
        use = (
            "from lib import Bad, Baz, Foo, Qux\n\n\n"
            "def build():\n    return Foo(1)\n\n\n"
            "def sub():\n    return Baz(3)\n\n\n"
            "def own():\n    return Qux()\n\n\n"
            "def mixed():\n    return Bad(4)\n\n\n"
            "def typed(f: Foo) -> bool:\n    return isinstance(f, Foo)\n\n\n"
            "def static():\n    return Foo.make()\n"
        )
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": lib.replace("self.n = n", "self.n = int(n)")})
        m = self.repo.build()
        init = box_id("lib.py", "Foo.__init__")
        self.assertEqual(m.certainty(box_id("use.py", "build"), init), "exact")
        self.assertEqual(m.certainty(box_id("use.py", "sub"), init), "exact", "Baz has no __init__")
        self.assertEqual(m.certainty(box_id("lib.py", "Qux.__init__"), init), "exact", "super().__init__")
        self.assertIsNone(m.arrow(box_id("use.py", "own"), init), "Qux() runs Qux.__init__")
        self.assertIsNone(m.arrow(box_id("use.py", "mixed"), init), "Bad(4) runs Mixin.__init__ first")
        self.assertIsNone(m.arrow(box_id("use.py", "typed"), init), "an annotation and isinstance are not calls")
        self.assertIsNone(m.arrow(box_id("use.py", "static"), init), "Foo.make() does not construct directly")
        self.assertEqual(m.certainty(box_id("lib.py", "Foo.make"), init), "possible", "cls(0)")

    def test_class_changed_by_a_field_keeps_its_callers(self):  # [pr-map AC-4]
        lib = "class Foo:\n    limit = 1\n\n    def __init__(self, n):\n        self.n = n\n"
        use = "from lib import Foo\n\n\ndef build():\n    return Foo(1)\n"
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": lib.replace("limit = 1", "limit = 2")})
        m = self.repo.build()
        self.assertEqual(m.certainty(box_id("use.py", "build"), box_id("lib.py", "Foo")), "exact")

    def test_callers_of_a_removed_function_stay_visible(self):  # [pr-map AC-3]
        lib = "def gone():\n    return 1\n\n\ndef stay():\n    return 2\n"
        use = "from lib import gone\n\n\ndef caller():\n    return gone()\n"
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": "def stay():\n    return 2\n"})
        m = self.repo.build()
        gone = box_id("lib.py", "gone")
        self.assertEqual(m.status("lib.py", "gone"), "removed")
        arrow = m.arrow(box_id("use.py", "caller"), gone)
        self.assertIsNotNone(arrow, "a caller still calling a removed function is what a reviewer must see")
        self.assertEqual(arrow["certainty"], "possible")

    def test_callers_of_a_removed_constructor_are_listed(self):  # [pr-map AC-3] [pr-map AC-11]
        lib = "class Foo:\n    def __init__(self, a, b):\n        self.a = a\n"
        use = "from lib import Foo\n\n\ndef build():\n    return Foo(1, 2)\n"
        self.repo.base({"lib.py": lib, "use.py": use})
        self.repo.head({"lib.py": "class Foo:\n    pass\n"})
        m = self.repo.build()
        self.assertEqual(m.status("lib.py", "Foo.__init__"), "removed")
        self.assertIsNone(m.arrow(box_id("use.py", "build"), box_id("lib.py", "Foo.__init__")))
        self.assertIn(self.repo.site("use.py", "Foo(1, 2)"), m.comment, "the call is listed as possibly broken")

    def test_every_arrow_matches_a_listed_reference(self):  # [pr-map AC-7]
        lib = (
            "class Base:\n    def run(self):\n        return 0\n\n\n"
            "class Impl(Base):\n    def run(self):\n        return 1\n\n\n"
            "def run():\n    return 9\n\n\n"
            "def go(b: Base, x):\n    return b.run(), x.run(), run()\n"
        )
        self.repo.base({"lib.py": lib})
        self.repo.head({"lib.py": lib.replace("        return 1\n", "        return 2\n")})
        m = self.repo.build()
        line = self.repo.site("lib.py", "return b.run(), x.run(), run()")
        self.assertTrue(m.arrows(target=box_id("lib.py", "Impl.run")), "go may call Impl.run")
        m.check_against(self, {line: UNCERTAIN})


if __name__ == "__main__":
    unittest.main()
