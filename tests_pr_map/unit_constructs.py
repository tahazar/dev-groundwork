"""Tests for constructs.py. Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import constructs


def parse(path: str, text: str) -> constructs.FileConstructs:
    return constructs.parse(path, text.encode("utf-8"))


def by_id(parsed: constructs.FileConstructs) -> dict[str, constructs.Construct]:
    return {c.id: c for c in parsed.constructs}


class QualifiedNameTests(unittest.TestCase):
    def test_python_methods_and_nested_functions(self):
        parsed = parse(
            "pkg/lib.py",
            "class Shape:\n"
            "    def area(self):\n"
            "        def unit():\n"
            "            return 1\n"
            "        return unit()\n"
            "\n"
            "\n"
            "def outer():\n"
            "    def inner():\n"
            "        return 0\n"
            "    return inner\n",
        )
        self.assertEqual(
            [c.id for c in parsed.constructs],
            [
                "pkg/lib.py::Shape",
                "pkg/lib.py::Shape.area",
                "pkg/lib.py::Shape.area.unit",
                "pkg/lib.py::outer",
                "pkg/lib.py::outer.inner",
            ],
        )
        self.assertEqual(by_id(parsed)["pkg/lib.py::Shape.area"].path, "pkg/lib.py")

    def test_typescript_classes_interfaces_and_object_literals(self):
        parsed = parse(
            "src/lib.ts",
            "export interface Base {\n  run(): void;\n}\n"
            "export class Impl implements Base {\n  run(): void {}\n}\n"
            "export const fake: Base = {\n  run() {},\n  stop: () => 1,\n};\n"
            "export const arrow = (x: number) => x;\n",
        )
        self.assertEqual(
            [c.name for c in parsed.constructs],
            ["Base", "Base.run", "Impl", "Impl.run", "fake.run", "fake.stop", "arrow"],
        )

    def test_tsx_component(self):
        parsed = parse("src/view.tsx", "export function View(): JSX.Element {\n  return <Item a={1} />;\n}\n")
        self.assertEqual([c.id for c in parsed.constructs], ["src/view.tsx::View"])
        self.assertIn("Item", [s.name for s in parsed.sites])
        self.assertEqual(parsed.error_lines, ())


class KindTests(unittest.TestCase):
    def test_python_kinds(self):
        text = "class C:\n    def m(self):\n        def f():\n            pass\n\n\ndef g():\n    pass\n"
        parsed = by_id(parse("a.py", text))
        kinds = {i.removeprefix("a.py::"): c.kind for i, c in parsed.items()}
        self.assertEqual(kinds, {"C": "class", "C.m": "method", "C.m.f": "function", "g": "function"})

    def test_typescript_member_kinds(self):
        parsed = by_id(
            parse(
                "a.ts",
                "interface I {\n  m(): void;\n  p: number;\n  q: () => void;\n}\n"
                "abstract class A {\n  abstract k(): void;\n  h = () => 1;\n  data = 2;\n  run() {}\n}\n"
                "function f() {}\n",
            )
        )
        kinds = {i.removeprefix("a.ts::"): c.kind for i, c in parsed.items()}
        self.assertEqual(
            kinds,
            {
                "I": "class",
                "I.m": "member",
                "I.p": "member",
                "I.q": "member",
                "A": "class",
                "A.k": "member",
                "A.h": "member",
                "A.run": "method",
                "f": "function",
            },
            "a class field holding data is not a construct",
        )


class NestingTests(unittest.TestCase):
    def test_parent_is_the_innermost_construct(self):
        parsed = by_id(parse("a.py", "class C:\n    def m(self):\n        def f():\n            pass\n"))
        self.assertIsNone(parsed["a.py::C"].parent)
        self.assertEqual(parsed["a.py::C.m"].parent, "a.py::C")
        self.assertEqual(parsed["a.py::C.m.f"].parent, "a.py::C.m")

    def test_site_belongs_to_the_innermost_construct(self):
        parsed = parse(
            "a.py",
            "import os\n\n\nclass C(Base):\n    size = helper()\n\n"
            "    @wrap\n    def m(self):\n        def f():\n            return go()\n        return stop()\n",
        )
        owners = {s.name: s.owner for s in parsed.sites}
        self.assertIsNone(owners["os"], "module level")
        self.assertEqual(owners["Base"], "a.py::C", "the heritage clause belongs to the class")
        self.assertEqual(owners["helper"], "a.py::C", "a class-level line belongs to the class")
        self.assertEqual(owners["wrap"], "a.py::C.m", "a decorator belongs to what it decorates")
        self.assertEqual(owners["go"], "a.py::C.m.f")
        self.assertEqual(owners["stop"], "a.py::C.m")

    def test_span_includes_decorators_and_export(self):
        py = by_id(parse("a.py", "class C:\n    @property\n    def m(self):\n        return 1\n"))
        self.assertEqual((py["a.py::C.m"].start_line, py["a.py::C.m"].end_line, py["a.py::C.m"].line), (2, 4, 3))
        ts = by_id(parse("a.ts", "@dec\nexport class K {\n  run() {}\n}\n"))
        self.assertEqual((ts["a.ts::K"].start_line, ts["a.ts::K"].end_line), (1, 4))

    def test_typescript_member_decorators_belong_to_the_member(self):
        parsed = parse("a.ts", "class A {\n  @log(helper)\n  // note\n  @x m(): void {}\n  n(): void {}\n}\n")
        m = by_id(parsed)["a.ts::A.m"]
        self.assertEqual((m.start_line, m.end_line, m.line), (2, 4, 4))
        self.assertEqual(by_id(parsed)["a.ts::A.n"].start_line, 5)
        owners = [(s.name, s.owner) for s in parsed.sites]
        self.assertEqual(owners, [("log", "a.ts::A.m"), ("helper", "a.ts::A.m"), ("x", "a.ts::A.m")])


class SiteTests(unittest.TestCase):
    def test_definition_names_are_not_sites(self):
        parsed = parse("a.py", "def f(x):\n    return f(x)\n")
        self.assertEqual(
            [(s.name, s.line, s.call) for s in parsed.sites], [("x", 1, False), ("f", 2, True), ("x", 2, False)]
        )

    def test_python_call_marks(self):
        parsed = parse("a.py", "def g():\n    np.mean(xs)\n    Foo(1)\n    run(key=fn)\n")
        calls = {s.name: s.call for s in parsed.sites}
        self.assertEqual(
            calls, {"np": False, "mean": True, "xs": False, "Foo": True, "run": True, "key": False, "fn": False}
        )

    def test_typescript_node_kinds_and_call_marks(self):
        parsed = parse(
            "a.ts",
            "class B extends A {\n  constructor() {\n    super(1);\n    new this();\n  }\n}\n"
            "function g(r: Rec): void {\n  const o = { run, key: cmdRun };\n  o.go();\n  new Foo();\n}\n",
        )
        sites = {s.name: s.call for s in parsed.sites}
        for name, call in {
            "A": False,
            "super": True,
            "this": True,
            "Rec": False,
            "run": False,
            "key": False,
            "cmdRun": False,
            "go": True,
            "Foo": True,
        }.items():
            self.assertEqual(sites.get(name), call, name)


class OverloadTests(unittest.TestCase):
    def test_signatures_and_implementation_are_one_construct(self):
        parsed = parse(
            "src/ov.ts",
            "export function ov(x: number): number;\n"
            "// a comment between overloads\n"
            "export function ov(x: string): string;\n"
            "export function ov(x: number | string): number | string {\n  return x;\n}\n"
            "export function other(): void {}\n",
        )
        ov = [c for c in parsed.constructs if c.name == "ov"]
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0].id, "src/ov.ts::ov")
        self.assertEqual(ov[0].names, ((1, 16), (3, 16), (4, 16)))
        self.assertEqual((ov[0].start_line, ov[0].end_line), (1, 6))
        self.assertEqual(ov[0].kind, "function")

    def test_method_overloads_are_one_method(self):
        parsed = parse("a.ts", "class C {\n  f(x: number): void;\n  f(x: any) {}\n  g() {}\n}\n")
        self.assertEqual(
            [(c.name, c.kind, len(c.names)) for c in parsed.constructs],
            [("C", "class", 1), ("C.f", "method", 2), ("C.g", "method", 1)],
        )

    def test_overloads_with_a_decorated_implementation_are_one_method(self):
        text = "class A {\n  m(a: string): void;\n  m(a: number): void;\n  @dec\n  m(a: any): void {}\n}\n"
        parsed = parse("a.ts", text)
        self.assertEqual(
            [(c.id, c.kind, c.names) for c in parsed.constructs][1:],
            [("a.ts::A.m", "method", ((2, 2), (3, 2), (5, 2)))],
        )

    def test_same_name_functions_that_are_not_overloads_stay_apart(self):
        parsed = parse("a.ts", "function f(): void {}\nfunction f(): void {}\n")
        self.assertEqual([c.id for c in parsed.constructs], ["a.ts::f", "a.ts::f#2"])


class OrdinalTests(unittest.TestCase):
    def test_repeated_names_get_ordinals_in_source_order(self):
        parsed = parse(
            "clip.py",
            "class Clip:\n"
            "    @property\n    def gain(self):\n        return self._g\n\n"
            "    @gain.setter\n    def gain(self, v):\n        self._g = v\n\n\n"
            "if X:\n    def run():\n        pass\nelse:\n    def run():\n        pass\n",
        )
        self.assertEqual(
            [(c.id, c.name, c.line) for c in parsed.constructs],
            [
                ("clip.py::Clip", "Clip", 1),
                ("clip.py::Clip.gain", "Clip.gain", 3),
                ("clip.py::Clip.gain#2", "Clip.gain", 7),
                ("clip.py::run", "run", 12),
                ("clip.py::run#2", "run", 15),
            ],
        )


class ColumnTests(unittest.TestCase):
    def test_char_column_counts_characters_not_bytes(self):
        text = "s = 'é😀'; f()"
        line = text.encode()
        byte_column = line.index(b"f()")
        self.assertEqual(byte_column - text.index("f()"), 4, "é is 2 bytes and 😀 is 4")
        self.assertEqual(constructs.char_column(line, byte_column), text.index("f()"))

    def test_construct_and_site_columns_are_characters(self):
        text = "const é = 'ü'; function ü(): string { return é; }"
        parsed = parse("a.ts", text + "\n")
        (fn,) = parsed.constructs
        self.assertEqual((fn.line, fn.column), (1, text.index("ü()")))
        self.assertEqual([(s.name, s.column) for s in parsed.sites], [("é", 6), ("é", text.rindex("é"))])

    def test_python_columns(self):
        parsed = parse("a.py", "x = 'ünï'; y = 1\ndef f(): return x\n")
        (fn,) = parsed.constructs
        self.assertEqual((fn.line, fn.column), (2, 4))
        self.assertEqual([(s.name, s.line, s.column) for s in parsed.sites][:2], [("x", 1, 0), ("y", 1, 11)])


class SyntaxErrorTests(unittest.TestCase):
    def test_broken_file_keeps_the_constructs_that_parse(self):
        broken = "def good():\n    return 3\n\n\ndef other(:\n    return 2\n\n\ndef after():\n    pass\n"
        parsed = parse("lib.py", broken)
        names = [c.name for c in parsed.constructs]
        self.assertIn("good", names)
        self.assertIn("after", names)
        self.assertEqual(parsed.error_lines, (5,))

    def test_missing_token_is_an_error_line(self):
        parsed = parse("a.ts", "function f() {\n  return g(1;\n}\n")
        self.assertTrue(parsed.error_lines)
        self.assertEqual([c.name for c in parsed.constructs], ["f"])

    def test_clean_file_has_no_error_lines(self):
        self.assertEqual(parse("a.py", "def f():\n    pass\n").error_lines, ())

    def test_non_utf8_source_is_unreadable(self):
        with self.assertRaisesRegex(constructs.UnreadableSource, r"bad\.py is not UTF-8") as caught:
            constructs.parse("bad.py", b"def f():\n    return '\xff\xfe'\n")
        self.assertIsInstance(caught.exception.__cause__, UnicodeDecodeError)


class ScanTests(unittest.TestCase):
    def test_scan_parses_every_source_file_outside_the_skip_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "a.py": b"def a():\n    pass\n",
                "src/b.ts": b"export function b() {}\n",
                "src/c.tsx": b"export function C() { return <div />; }\n",
                "node_modules/x/d.ts": b"export function d() {}\n",
                "README.md": b"# a\n",
                "bad.py": b"x = '\xff'\n",
            }
            for rel, data in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(data)
            parsed, unreadable = constructs.scan(root)
        self.assertEqual(sorted(parsed), ["a.py", "src/b.ts", "src/c.tsx"])
        self.assertEqual(list(unreadable), ["bad.py"])
        self.assertIn("not UTF-8", unreadable["bad.py"])


if __name__ == "__main__":
    unittest.main()
