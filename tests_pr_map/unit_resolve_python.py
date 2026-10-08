"""Tests for resolve.py on Python: jedi answers and the verdict table, on small temporary repositories.

Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import constructs
import resolve
from resolve import CALLEE, CALLER, REMOVED, Answer, Candidate, Code, Location, Verdict


class Repo:
    """Files in a temporary directory, with the constructs, Code and Resolver the verdicts need."""

    def __init__(self, testcase: unittest.TestCase, files: dict[str, str], removed: dict[str, str] | None = None):
        self.root = Path(tempfile.mkdtemp())
        testcase.addCleanup(shutil.rmtree, self.root)
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        self.files, unreadable = constructs.scan(self.root)
        testcase.assertEqual(unreadable, {})
        self.resolver = resolve.Resolver(self.root)
        by_id, positions = resolve.index(self.files.values())
        # Constructs of the base commit that are gone from the head: removed boxes.
        for rel, text in (removed or {}).items():
            for c in constructs.parse(rel, text.encode("utf-8")).constructs:
                by_id.setdefault(c.id, c)
        bases = {
            c.id: self.resolver.class_bases(c, positions)
            for c in by_id.values()
            if c.kind == "class" and c.id in positions.values()
        }
        self.code = Code(by_id, positions, bases)

    def site(self, rel: str, needle: str, name: str | None = None, occurrence: int = 1) -> constructs.Site:
        """The reference site named name (default: needle's first word) inside the occurrence-th line with needle."""
        lines = (self.root / rel).read_text(encoding="utf-8").splitlines()
        line = [i for i, text in enumerate(lines, 1) if needle in text][occurrence - 1]
        name = name or needle.split("(")[0].split(".")[-1].strip()
        column = lines[line - 1].index(needle) + needle.index(name)
        return next(s for s in self.files[rel].sites if (s.line, s.column) == (line, column))

    def judge(self, rel: str, needle: str, role: str, target: str | None = None, name: str | None = None) -> Verdict:
        s = self.site(rel, needle, name)
        candidate = Candidate(rel, s.line, s.column, s.name, s.call, role, target)
        answer = Answer(
            tuple(self.resolver.definition_at(rel, s.line, s.column)),
            traced=self.resolver.trace_import(rel, s.line, s.column),
        )
        named = [c.id for c in self.code.constructs.values() if c.name.rsplit(".", 1)[-1] == s.name]
        return resolve.verdict(candidate, answer, self.code, [n for n in named if n in self.code.positions.values()])


class DefinitionTests(unittest.TestCase):
    def test_call_resolves_to_the_function_name_position(self):
        repo = Repo(self, {"lib.py": "def target():\n    return 1\n", "use.py": "from lib import target\n\ntarget()\n"})
        s = repo.site("use.py", "target()")
        [loc] = repo.resolver.definition_at("use.py", s.line, s.column)
        self.assertEqual((loc.path, loc.line, loc.column, loc.kind), ("lib.py", 1, 4, "function"))

    def test_call_through_an_aliased_import_resolves_to_the_original(self):
        repo = Repo(
            self,
            {
                "report.py": "def save_record(p):\n    return p\n",
                "use.py": "from report import save_record as save\n\n\ndef caller():\n    return save(1)\n",
            },
        )
        v = repo.judge("use.py", "save(1)", CALLER, "report.py::save_record")
        self.assertEqual(v, Verdict("exact", "report.py::save_record"))

    def test_character_columns_after_non_ascii_text(self):
        use = 'from lib import target\n\n\ndef f():\n    return ("ééé", target())\n'
        repo = Repo(self, {"lib.py": "def target():\n    return 1\n", "use.py": use})
        s = repo.site("use.py", "target()")
        self.assertEqual(s.column, use.splitlines()[4].index("target"), "a character column, not a byte column")
        self.assertEqual(repo.judge("use.py", "target()", CALLER, "lib.py::target").certainty, "exact")

    def test_library_definition_is_outside_the_repository(self):
        repo = Repo(self, {"use.py": "import statistics\n\nstatistics.mean([1])\n"})
        s = repo.site("use.py", "mean(")
        [loc] = repo.resolver.definition_at("use.py", s.line, s.column)
        self.assertIsNone(loc.path)
        self.assertEqual(loc.name, "statistics.mean")

    def test_installed_package_inside_a_skipped_directory_is_outside_the_repository(self):
        repo = Repo(
            self,
            {
                ".venv/lib/python3/site-packages/vendored.py": "def mean(xs):\n    return 0\n",
                "use.py": "import sys\n"
                "sys.path.insert(0, '.venv/lib/python3/site-packages')\n"
                "from vendored import mean\n\nmean([1])\n",
            },
        )
        s = repo.site("use.py", "mean([1])")
        for loc in repo.resolver.definition_at("use.py", s.line, s.column):
            self.assertIsNone(loc.path, loc)

    def test_untyped_parameter_answers_nothing(self):
        lib = (
            "class A:\n    def save(self):\n        return 1\n\n\n"
            "class B:\n    def save(self):\n        return 2\n\n\n"
            "def store(obj):\n    return obj.save()\n\n\nstore(A())\n"
        )
        repo = Repo(self, {"lib.py": lib})
        s = repo.site("lib.py", "obj.save()", "save")
        self.assertEqual(repo.resolver.definition_at("lib.py", s.line, s.column), [], "C60: no inferred types")

    def test_parameter_and_local_are_local(self):
        lib = "def apply(fn):\n    x = fn\n    return x()\n"
        repo = Repo(self, {"lib.py": lib})
        [param] = repo.resolver.definition_at("lib.py", 2, 8)
        [variable] = repo.resolver.definition_at("lib.py", 3, 11)
        self.assertTrue(param.local)
        self.assertTrue(variable.local)

    def test_attribute_set_in_init_is_not_local(self):
        lib = (
            "class Clip:\n    def __init__(self):\n        self.notes = [1]\n\n"
            "    def count(self):\n        return self.notes\n"
        )
        repo = Repo(self, {"lib.py": lib})
        [loc] = repo.resolver.definition_at("lib.py", 6, 20)
        self.assertEqual((loc.path, loc.line, loc.local), ("lib.py", 3, False))

    def test_unsupported_file_and_bad_position_raise_resolver_error(self):
        repo = Repo(self, {"lib.py": "x = 1\n", "a.js": "export const x = 1;\n"})
        with self.assertRaisesRegex(resolve.ResolverError, r"a\.js:1:0: no resolver for \.js"):
            repo.resolver.definition_at("a.js", 1, 0)
        with self.assertRaisesRegex(resolve.ResolverError, r"jedi goto at lib\.py:1:40") as caught:
            repo.resolver.definition_at("lib.py", 1, 40)
        self.assertIsInstance(caught.exception.__cause__, ValueError)

    def test_references_include_the_renaming_import_but_not_the_definition(self):
        repo = Repo(
            self,
            {
                "report.py": "def save_record(p):\n    return p\n",
                "use.py": "from report import save_record as save\n\nsave(1)\n",
            },
        )
        found = repo.resolver.references("report.py", 1, 4)
        self.assertEqual([(loc.path, loc.line) for loc in found], [("use.py", 1)], "C46: not the call through it")

    def test_one_project_per_nearest_project_file(self):
        repo = Repo(self, {"sub/pyproject.toml": "", "sub/pkg/app.py": "x = 1\n", "top.py": "y = 2\n"})
        self.assertEqual(Path(repo.resolver._project("sub/pkg/app.py").path), repo.root.resolve() / "sub")
        self.assertEqual(Path(repo.resolver._project("top.py").path), repo.root.resolve())


class CallerVerdictTests(unittest.TestCase):
    def test_answer_at_the_target_is_exact(self):
        use = "from lib import target\n\n\ndef caller():\n    return target()\n"
        repo = Repo(self, {"lib.py": "def target():\n    return 1\n", "use.py": use})
        self.assertEqual(repo.judge("use.py", "target()", CALLER, "lib.py::target"), Verdict("exact", "lib.py::target"))

    def test_same_named_function_elsewhere_is_unrelated(self):
        repo = Repo(
            self,
            {
                "report.py": "def save_record(p):\n    return p\n",
                "drumstats.py": "def save_record(p):\n    return p\n",
                "main.py": "import drumstats\n\n\ndef b():\n    return drumstats.save_record(2)\n",
            },
        )
        self.assertEqual(repo.judge("main.py", "save_record(2)", CALLER, "report.py::save_record"), Verdict(""))

    def test_base_class_two_levels_up_is_related(self):
        lib = (
            "class Base:\n    def run(self):\n        return 0\n\n\n"
            "class Mid(Base):\n    pass\n\n\n"
            "class Impl(Mid):\n    def run(self):\n        return 1\n\n\n"
            "def go(b: Base):\n    return b.run()\n"
        )
        repo = Repo(self, {"lib.py": lib})
        v = repo.judge("lib.py", "b.run()", CALLER, "lib.py::Impl.run", "run")
        self.assertEqual(v, Verdict("possible", "lib.py::Impl.run", "through `lib.py::Base.run`"))

    def test_protocol_member_is_related(self):
        lib = (
            "from typing import Protocol\n\n\n"
            "class Runner(Protocol):\n    def run(self) -> int: ...\n\n\n"
            "class Job:\n    def run(self) -> int:\n        return 1\n\n\n"
            "def go(r: Runner) -> int:\n    return r.run()\n"
        )
        repo = Repo(self, {"lib.py": lib})
        v = repo.judge("lib.py", "r.run()", CALLER, "lib.py::Job.run", "run")
        self.assertEqual(v, Verdict("possible", "lib.py::Job.run", "through `lib.py::Runner.run`"))

    def test_untyped_parameter_is_possible(self):
        lib = (
            "class A:\n    def save(self):\n        return 1\n\n\n"
            "class B:\n    def save(self):\n        return 2\n\n\n"
            "def store(obj):\n    return obj.save()\n\n\nstore(A())\n"
        )
        repo = Repo(self, {"lib.py": lib, "other.py": "from lib import B, store\n\nstore(B())\n"})
        v = repo.judge("lib.py", "obj.save()", CALLER, "lib.py::B.save", "save")
        self.assertEqual(v, Verdict("possible", "lib.py::B.save", "unresolved"))

    def test_local_variable_with_the_name_draws_nothing(self):
        lib = "def handler():\n    return 1\n\n\ndef make():\n    return lambda: 2\n"
        use = "from lib import handler, make\n\n\ndef run():\n    handler = make()\n    return handler()\n"
        repo = Repo(self, {"lib.py": lib, "use.py": use})
        self.assertEqual(repo.judge("use.py", "return handler()", CALLER, "lib.py::handler", "handler"), Verdict(""))

    def test_attribute_is_listed_as_a_non_box_reference(self):
        lib = (
            "def notes():\n    return []\n\n\n"
            "class Clip:\n    def __init__(self):\n        self.notes = [1]\n\n"
            "    def count(self):\n        return len(self.notes)\n"
        )
        repo = Repo(self, {"lib.py": lib})
        v = repo.judge("lib.py", "self.notes)", CALLER, "lib.py::notes", "notes")
        self.assertEqual(v, Verdict("", note="refers", refers_to="lib.py:7"))

    def test_library_call_is_counted_not_drawn(self):
        lib = "def mean(xs):\n    return 0\n"
        use = "import numpy as np\n\n\ndef stats(xs):\n    arr = np.array(xs)\n    return np.mean(xs), arr.mean()\n"
        repo = Repo(self, {"lib.py": lib, "use.py": use})
        self.assertEqual(
            repo.judge("use.py", "np.mean(xs)", CALLER, "lib.py::mean", "mean"), Verdict("", note="library")
        )
        self.assertEqual(
            repo.judge("use.py", "arr.mean()", CALLER, "lib.py::mean", "mean"), Verdict("", note="library")
        )

    def test_standard_library_call_draws_nothing(self):
        lib = "def mean(xs):\n    return 0\n"
        use = "import statistics\n\n\ndef stats(xs):\n    return statistics.mean(xs)\n"
        repo = Repo(self, {"lib.py": lib, "use.py": use})
        self.assertEqual(repo.judge("use.py", "statistics.mean(xs)", CALLER, "lib.py::mean", "mean"), Verdict(""))

    def test_unresolved_import_of_a_repository_module_is_possible(self):
        lib = "def target():\n    return 1\n"
        use = "from lib import ghost as target\n\n\ndef caller():\n    return target()\n"
        repo = Repo(self, {"lib.py": lib, "use.py": use})
        v = repo.judge("use.py", "return target()", CALLER, "lib.py::target", "target")
        self.assertEqual(v, Verdict("possible", "lib.py::target", "unresolved import"))

    def test_resolver_failure_is_possible_with_the_reason(self):
        repo = Repo(self, {"lib.py": "def target():\n    return 1\n"})
        candidate = Candidate("a.ts", 1, 0, "target", True, CALLER, "lib.py::target")
        v = resolve.verdict(candidate, Answer(error="no resolver for .ts files yet"), repo.code)
        self.assertEqual(v, Verdict("possible", "lib.py::target", "resolver failed: no resolver for .ts files yet"))

    def test_several_unrelated_boxes_are_possible(self):
        lib = "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef target():\n    return 3\n"
        repo = Repo(self, {"lib.py": lib})
        candidate = Candidate("lib.py", 1, 0, "target", True, CALLER, "lib.py::target")
        answer = Answer((Location("lib.py", 1, 4, "function", "lib.a"), Location("lib.py", 5, 4, "function", "lib.b")))
        self.assertEqual(
            resolve.verdict(candidate, answer, repo.code), Verdict("possible", "lib.py::target", "unresolved")
        )

    def test_runtime_class_is_possible(self):
        repo = Repo(self, {"lib.py": "class Foo:\n    def __init__(self):\n        pass\n"})
        candidate = Candidate("lib.py", 1, 0, "cls", True, CALLER, "lib.py::Foo.__init__", through="cls")
        v = resolve.verdict(candidate, Answer(), repo.code)
        self.assertEqual(v, Verdict("possible", "lib.py::Foo.__init__", "through `cls`"))

    def test_target_among_several_boxes_is_possible(self):
        lib = (
            "class A:\n    def save(self):\n        return 1\n\n\n"
            "class B:\n    def save(self):\n        return 2\n\n\n"
            "def store(obj: A | B):\n    return obj.save()\n"
        )
        repo = Repo(self, {"lib.py": lib})
        s = repo.site("lib.py", "obj.save()", "save")
        self.assertEqual(len(repo.resolver.definition_at("lib.py", s.line, s.column)), 2, "jedi answers both")
        v = repo.judge("lib.py", "obj.save()", CALLER, "lib.py::A.save", "save")
        self.assertEqual(v, Verdict("possible", "lib.py::A.save", "unresolved"))

    def test_module_reached_through_sys_path_is_not_a_library(self):
        lib = "def target():\n    return 1\n"
        use = (
            "import sys\n\nsys.path.insert(0, 'scripts/tool')\nimport lib\n\n\ndef caller():\n    return lib.target()\n"
        )
        repo = Repo(self, {"scripts/tool/lib.py": lib, "tests/t.py": use})
        s = repo.site("tests/t.py", "lib.target()", "target")
        self.assertEqual(repo.resolver.trace_import("tests/t.py", s.line, s.column), "repository")

    def test_comprehension_variable_is_not_traced_to_an_outer_binding(self):
        use = "import numpy as np\n\nx = np.zeros(3)\n\n\ndef f(items):\n    return [x.save() for x in items]\n"
        repo = Repo(self, {"use.py": use})
        s = repo.site("use.py", "x.save()", "save")
        self.assertEqual(repo.resolver.trace_import("use.py", s.line, s.column), "")

    def test_splat_parameters_are_bindings(self):
        use = (
            "import numpy as np\n\nargs = np.zeros(3)\n\n\n"
            "def f(*args: np.ndarray, **kw):\n    return args.save(), kw.save()\n"
        )
        repo = Repo(self, {"use.py": use})
        for needle in ("args.save()", "kw.save()"):
            s = repo.site("use.py", needle, "save")
            self.assertEqual(repo.resolver.trace_import("use.py", s.line, s.column), "", needle)

    def test_callee_refers_and_resolver_failure(self):
        lib = (
            "def notes():\n    return []\n\n\n"
            "class Clip:\n    def __init__(self):\n        self.notes = [1]\n\n"
            "    def count(self):\n        return len(self.notes)\n"
        )
        repo = Repo(self, {"lib.py": lib})
        v = repo.judge("lib.py", "self.notes)", CALLEE, name="notes")
        self.assertEqual(v, Verdict("", note="refers", refers_to="lib.py:7"))
        candidate = Candidate("lib.py", 10, 0, "notes", True, CALLEE)
        v = resolve.verdict(candidate, Answer(error="boom"), repo.code, ["lib.py::notes"])
        self.assertEqual(v, Verdict("possible", "lib.py::notes", "resolver failed: boom"))

    def test_removed_target_library_and_local_answers_draw_nothing(self):
        repo = Repo(self, {"lib.py": "def stay():\n    return 2\n"})
        candidate = Candidate("lib.py", 1, 0, "gone", True, REMOVED, "lib.py::gone")
        self.assertEqual(resolve.verdict(candidate, Answer(traced="library"), repo.code), Verdict("", note="library"))
        local = Answer((Location("lib.py", 1, 0, "param", "x", local=True),))
        self.assertEqual(resolve.verdict(candidate, local, repo.code), Verdict(""))


CONSTRUCTORS = (
    "class Foo:\n"
    "    def __init__(self, n):\n        self.n = n\n\n"
    "    @classmethod\n    def make(cls):\n        return cls(0)\n\n\n"
    "class Baz(Foo):\n    pass\n\n\n"
    "class Qux(Foo):\n    def __init__(self):\n        super().__init__(2)\n\n\n"
    "class Mixin:\n    def __init__(self, n):\n        self.m = n\n\n\n"
    "class Bad(Mixin, Foo):\n    pass\n"
)
CONSTRUCTOR_USES = (
    "from lib import Bad, Baz, Foo, Qux\n\n\n"
    "def build():\n    return Foo(1)\n\n\n"
    "def sub():\n    return Baz(3)\n\n\n"
    "def own():\n    return Qux()\n\n\n"
    "def mixed():\n    return Bad(4)\n\n\n"
    "def typed(f: Foo) -> bool:\n    return isinstance(f, Foo)\n\n\n"
    "def static():\n    return Foo.make()\n"
)


class ConstructorTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self, {"lib.py": CONSTRUCTORS, "use.py": CONSTRUCTOR_USES})

    def judge(self, needle: str, name: str, target: str = "lib.py::Foo.__init__") -> Verdict:
        return self.repo.judge("use.py", needle, CALLER, target, name)

    def test_call_of_the_class_and_of_a_subclass_runs_init(self):
        self.assertEqual(self.judge("Foo(1)", "Foo"), Verdict("exact", "lib.py::Foo.__init__"))
        self.assertEqual(self.judge("Baz(3)", "Baz"), Verdict("exact", "lib.py::Foo.__init__"))

    def test_super_init_resolves_to_init(self):
        v = self.repo.judge("lib.py", "super().__init__(2)", CALLER, "lib.py::Foo.__init__", "__init__")
        self.assertEqual(v, Verdict("exact", "lib.py::Foo.__init__"))

    def test_own_init_or_a_mixin_first_takes_the_class_out(self):
        self.assertEqual(self.judge("Qux()", "Qux"), Verdict(""))
        self.assertEqual(self.judge("Bad(4)", "Bad"), Verdict(""))

    def test_annotation_isinstance_and_class_attribute_are_not_calls(self):
        self.assertEqual(self.judge("f: Foo", "Foo"), Verdict(""))
        self.assertEqual(self.judge("isinstance(f, Foo)", "Foo"), Verdict(""))
        self.assertEqual(self.judge("Foo.make()", "Foo"), Verdict(""))

    def test_class_target_counts_a_class_answer(self):
        self.assertEqual(self.judge("Foo(1)", "Foo", "lib.py::Foo"), Verdict("exact", "lib.py::Foo"))
        self.assertEqual(self.judge("f: Foo", "Foo", "lib.py::Foo"), Verdict("exact", "lib.py::Foo"))

    def test_callee_call_of_a_class_is_its_constructor_else_the_class(self):
        v = self.repo.judge("use.py", "Foo(1)", CALLEE, None, "Foo")
        self.assertEqual(v, Verdict("exact", "lib.py::Foo.__init__"))
        self.assertEqual(self.repo.judge("use.py", "Baz(3)", CALLEE, None, "Baz"), Verdict("exact", "lib.py::Baz"))

    def test_runners(self):
        found = resolve.runners("lib.py::Foo", "__init__", self.repo.code)
        self.assertEqual(found, {"lib.py::Foo": "", "lib.py::Baz": ""})

    def test_base_outside_the_repository_first_makes_the_call_possible(self):
        lib = (
            "import json\n\n\nclass Foo:\n    def __init__(self):\n        pass\n\n\n"
            "class Dec(json.JSONDecoder, Foo):\n    pass\n"
        )
        repo = Repo(self, {"lib.py": lib, "use.py": "from lib import Dec\n\nDec()\n"})
        v = repo.judge("use.py", "Dec()", CALLER, "lib.py::Foo.__init__", "Dec")
        self.assertEqual(v, Verdict("possible", "lib.py::Foo.__init__", "through `json.decoder.JSONDecoder`"))

    def test_decorated_subclass_may_generate_its_own_init(self):
        lib = (
            "from dataclasses import dataclass\n\n\nclass Foo:\n    def __init__(self, n):\n        self.n = n\n\n\n"
            "@dataclass\nclass Baz(Foo):\n    x: int\n"
        )
        repo = Repo(self, {"lib.py": lib, "use.py": "from lib import Baz\n\nBaz(3)\n"})
        v = repo.judge("use.py", "Baz(3)", CALLER, "lib.py::Foo.__init__", "Baz")
        self.assertEqual(v, Verdict("possible", "lib.py::Foo.__init__", "through `lib.py::Baz`"))

    def test_call_of_a_class_whose_init_was_removed_is_listed(self):
        repo = Repo(
            self,
            {
                "lib.py": "class Foo:\n    pass\n",
                "use.py": "from lib import Foo\n\n\ndef build():\n    return Foo(1, 2)\n",
            },
            removed={"lib.py": "class Foo:\n    def __init__(self, a, b):\n        self.a = a\n"},
        )
        v = repo.judge("use.py", "Foo(1, 2)", REMOVED, "lib.py::Foo.__init__", "Foo")
        self.assertEqual(v, Verdict("", target="lib.py::Foo.__init__", note="removed constructor"))


class CalleeVerdictTests(unittest.TestCase):
    def test_callee_answer_at_a_box_is_exact(self):
        lib = "def leaf():\n    return 1\n\n\ndef target():\n    return leaf()\n"
        repo = Repo(self, {"lib.py": lib})
        self.assertEqual(repo.judge("lib.py", "return leaf()", CALLEE, name="leaf"), Verdict("exact", "lib.py::leaf"))

    def test_callee_parameter_on_the_name_line_is_not_the_function(self):
        repo = Repo(self, {"lib.py": "def apply(fn):\n    return fn()\n"})
        self.assertEqual(repo.judge("lib.py", "fn()", CALLEE), Verdict(""))

    def test_callee_related_box_is_exact_to_that_box(self):
        lib = (
            "class Base:\n    def run(self):\n        return 0\n\n\n"
            "class Impl(Base):\n    def run(self):\n        return 1\n\n\n"
            "def go(b: Base):\n    return b.run()\n"
        )
        repo = Repo(self, {"lib.py": lib})
        self.assertEqual(repo.judge("lib.py", "b.run()", CALLEE, name="run"), Verdict("exact", "lib.py::Base.run"))

    def test_unresolved_callee_with_one_named_box_is_possible(self):
        lib = "class A:\n    def save(self):\n        return 1\n\n\ndef store(obj):\n    return obj.save()\n"
        repo = Repo(self, {"lib.py": lib})
        v = repo.judge("lib.py", "obj.save()", CALLEE, name="save")
        self.assertEqual(v, Verdict("possible", "lib.py::A.save", "unresolved"))

    def test_unresolved_callee_with_several_named_boxes_is_listed(self):
        lib = (
            "class A:\n    def save(self):\n        return 1\n\n\n"
            "class B:\n    def save(self):\n        return 2\n\n\n"
            "def store(obj):\n    return obj.save()\n"
        )
        repo = Repo(self, {"lib.py": lib})
        v = repo.judge("lib.py", "obj.save()", CALLEE, name="save")
        self.assertEqual(
            v, Verdict("", reason="unresolved", note="unresolved", options=("lib.py::A.save", "lib.py::B.save"))
        )

    def test_callee_library_call_is_counted(self):
        lib = "def mean(xs):\n    return 0\n\n\ndef stats(xs):\n    import numpy\n    return numpy.mean(xs)\n"
        repo = Repo(self, {"lib.py": lib})
        self.assertEqual(repo.judge("lib.py", "numpy.mean(xs)", CALLEE, name="mean"), Verdict("", note="library"))


class RemovedVerdictTests(unittest.TestCase):
    def test_caller_of_a_removed_function_is_possible(self):
        repo = Repo(
            self,
            {
                "lib.py": "def stay():\n    return 2\n",
                "use.py": "from lib import gone\n\n\ndef caller():\n    return gone()\n",
            },
            removed={"lib.py": "def gone():\n    return 1\n\n\ndef stay():\n    return 2\n"},
        )
        v = repo.judge("use.py", "gone()", REMOVED, "lib.py::gone")
        self.assertEqual(v, Verdict("possible", "lib.py::gone", "unresolved"))

    def test_name_now_resolving_to_another_box_draws_nothing(self):
        repo = Repo(
            self,
            {
                "lib.py": "def stay():\n    return 2\n",
                "use.py": "from lib import stay as gone\n\n\ndef caller():\n    return gone()\n",
            },
            removed={"lib.py": "def gone():\n    return 1\n\n\ndef stay():\n    return 2\n"},
        )
        self.assertEqual(repo.judge("use.py", "gone()", REMOVED, "lib.py::gone"), Verdict(""))


class TraceTests(unittest.TestCase):
    def trace(self, source: str, needle: str, name: str, files: dict[str, str] | None = None) -> str:
        repo = Repo(self, {"use.py": source, **(files or {})})
        s = repo.site("use.py", needle, name)
        return repo.resolver.trace_import("use.py", s.line, s.column)

    def test_import_of_a_module_not_in_the_repository_is_a_library(self):
        self.assertEqual(self.trace("import numpy as np\n\nnp.mean(1)\n", "np.mean", "mean"), "library")

    def test_import_of_a_repository_module(self):
        files = {"pkg/__init__.py": "", "lib.py": ""}
        self.assertEqual(self.trace("import pkg.sub\n\npkg.sub.f()\n", "sub.f", "f", files), "repository")
        self.assertEqual(self.trace("from lib import g\n\ng()\n", "g()", "g", files), "repository")
        self.assertEqual(self.trace("from . import h\n\nh()\n", "h()", "h"), "repository")

    def test_module_under_a_project_root_or_its_src_is_in_the_repository(self):
        files = {"sub/pyproject.toml": "", "sub/src/tool.py": ""}
        self.assertEqual(self.trace("import tool\n\ntool.run()\n", "tool.run", "run", files), "repository")

    def test_variable_assigned_once_follows_its_value(self):
        source = "import numpy as np\n\n\ndef f(xs):\n    arr = np.array(xs)\n    return arr.mean()\n"
        self.assertEqual(self.trace(source, "arr.mean", "mean"), "library")

    def test_variable_assigned_twice_is_not_traced(self):
        source = "import numpy as np\n\n\ndef f(xs):\n    arr = np.array(xs)\n    arr = xs\n    return arr.mean()\n"
        self.assertEqual(self.trace(source, "arr.mean", "mean"), "")

    def test_typed_parameter_follows_its_annotation(self):
        source = "from commander import Command\n\n\ndef f(cmd: Command):\n    return cmd.action()\n"
        self.assertEqual(self.trace(source, "cmd.action", "action"), "library")

    def test_untyped_parameter_is_not_traced(self):
        source = "import numpy as np\n\n\ndef f(arr):\n    return arr.mean()\n"
        self.assertEqual(self.trace(source, "arr.mean", "mean"), "")

    def test_only_one_assignment_is_followed(self):
        source = "import numpy as np\n\n\ndef f(xs):\n    a = np.array(xs)\n    b = a\n    return b.mean()\n"
        self.assertEqual(self.trace(source, "b.mean", "mean"), "")

    def test_other_languages_are_not_traced(self):
        repo = Repo(self, {"a.js": "export const x = 1;\n"})
        with self.assertRaisesRegex(resolve.ResolverError, r"tracing imports in a\.js: no resolver for \.js"):
            repo.resolver.trace_import("a.js", 1, 13)


class MroTests(unittest.TestCase):
    def test_c3_order_of_a_diamond(self):
        bases = {"D": ("B", "C"), "B": ("A",), "C": ("A",), "A": ()}
        self.assertEqual(resolve.mro("D", bases), ["D", "B", "C", "A"])

    def test_inconsistent_order_raises(self):
        bases = {"X": ("A", "B"), "Y": ("B", "A"), "Z": ("X", "Y"), "A": (), "B": ()}
        with self.assertRaisesRegex(ValueError, "cannot order the bases of Z"):
            resolve.mro("Z", bases)

    def test_cycle_raises(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            resolve.mro("A", {"A": ("B",), "B": ("A",)})

    def test_unknown_bases_are_leaves(self):
        self.assertEqual(resolve.mro("A", {"A": ("typing.Protocol",)}), ["A", "typing.Protocol"])


class BasesTests(unittest.TestCase):
    def test_bases_resolve_to_boxes_or_outside_names(self):
        lib = (
            "from typing import Generic, TypeVar\nimport other\n\nT = TypeVar('T')\n\n\n"
            "class Mine(other.Base, Generic[T], Missing, metaclass=type):\n    pass\n"
        )
        repo = Repo(self, {"lib.py": lib, "other.py": "class Base:\n    pass\n"})
        found, generic, missing = repo.code.bases["lib.py::Mine"]
        self.assertEqual((found, missing), ("other.py::Base", "Missing"))
        self.assertTrue(generic.endswith("typing.Generic"), generic)


if __name__ == "__main__":
    unittest.main()
