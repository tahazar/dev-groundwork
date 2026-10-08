"""Arrows in TypeScript code (AC-3 to AC-7, AC-9).

The TypeScript resolver runs on the pinned compiler in scripts/pr_map
(`npm ci --prefix scripts/pr_map`). Fixtures do not install their own
dependencies, as in CI.
"""

from __future__ import annotations

import json
import unittest

from helpers import UNCERTAIN, MapRepo, box_id

TSCONFIG = json.dumps(
    {
        "compilerOptions": {
            "target": "ES2022",
            "module": "NodeNext",
            "moduleResolution": "NodeNext",
            "strict": True,
            "rootDir": "src",
            "outDir": "dist",
            "declaration": True,
        },
        "include": ["src"],
    }
)


def package(name: str) -> str:
    return json.dumps({"name": name, "type": "module", "types": "./dist/index.d.ts"})


class TypeScriptArrowTests(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)

    def project(self, files: dict[str, str]) -> dict[str, str]:
        return {"tsconfig.json": TSCONFIG, **files}

    def test_callers_and_callees_one_step_each_way(self):  # [pr-map AC-4] [pr-map AC-5]
        lib = (
            "export function leaf(): number {\n  return 1;\n}\n"
            "export function target(): number {\n  return leaf();\n}\n"
        )
        use = 'import { target } from "./lib.js";\nexport function caller(): number {\n  return target();\n}\n'
        self.repo.base(self.project({"src/lib.ts": lib, "src/use.ts": use}))
        self.repo.head({"src/lib.ts": lib.replace("return leaf();", "return leaf() + 1;")})
        m = self.repo.build()
        target = box_id("src/lib.ts", "target")
        self.assertEqual(m.certainty(box_id("src/use.ts", "caller"), target), "exact")
        self.assertEqual(m.certainty(target, box_id("src/lib.ts", "leaf")), "exact")

    def test_renamed_and_default_imports(self):  # [pr-map AC-4] [pr-map AC-5]
        lib = (
            "export function readClip(): number {\n  return 1;\n}\n"
            "export default function loadSet(): number {\n  return 2;\n}\n"
        )
        use = (
            'import loader, { readClip as rc } from "./lib.js";\n'
            "export function a(): number {\n  return rc();\n}\n"
            "export function b(): number {\n  return loader();\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib, "src/use.ts": use}))
        self.repo.head({"src/lib.ts": lib.replace("return 1;", "return 3;").replace("return 2;", "return 4;")})
        m = self.repo.build()
        self.assertEqual(m.certainty(box_id("src/use.ts", "a"), box_id("src/lib.ts", "readClip")), "exact")
        self.assertEqual(m.certainty(box_id("src/use.ts", "b"), box_id("src/lib.ts", "loadSet")), "exact")

    def test_workspace_package_resolves_to_source_without_a_build(self):  # [pr-map AC-5]
        core_ts = TSCONFIG
        files = {
            "packages/core/package.json": package("@x/core"),
            "packages/core/tsconfig.json": core_ts,
            "packages/core/src/index.ts": "export function parse(s: string): number {\n  return s.length;\n}\n",
            "packages/cli/package.json": package("@x/cli"),
            "packages/cli/tsconfig.json": core_ts,
            "packages/cli/src/index.ts": (
                'import { parse } from "@x/core";\nexport function run(): number {\n  return parse("a");\n}\n'
            ),
        }
        self.repo.base(files)
        core = files["packages/core/src/index.ts"]
        self.repo.head({"packages/core/src/index.ts": core.replace("s.length", "s.length + 1")})
        m = self.repo.build()
        arrow = m.arrow(box_id("packages/cli/src/index.ts", "run"), box_id("packages/core/src/index.ts", "parse"))
        self.assertIsNotNone(arrow, "no dist/ exists; the paths mapping must point at core's source")
        self.assertEqual(arrow["certainty"], "exact")

    def test_test_file_outside_tsconfig_include(self):  # [pr-map AC-4]
        lib = "export function total(xs: number[]): number {\n  return xs.length;\n}\n"
        test = 'import { total } from "../src/lib.js";\nexport function checks(): number {\n  return total([1]);\n}\n'
        self.repo.base(self.project({"src/lib.ts": lib, "test/lib.test.ts": test}))
        self.repo.head({"src/lib.ts": lib.replace("xs.length", "xs.length * 2")})
        m = self.repo.build()
        arrow = m.arrow(box_id("test/lib.test.ts", "checks"), box_id("src/lib.ts", "total"))
        self.assertIsNotNone(arrow)
        self.assertEqual(arrow["certainty"], "exact")

    def test_call_through_interfaces_and_object_literals_is_possible(self):  # [pr-map AC-6]
        lib = (
            "export interface Base {\n  run(): void;\n}\n"
            "export class Mid implements Base {\n  run(): void {}\n}\n"
            "export class Impl extends Mid {\n  run(): void {\n    return;\n  }\n}\n"
            "export const fake: Base = {\n  run() {\n    return;\n  },\n};\n"
            "export function go(b: Base): void {\n  b.run();\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib}))
        self.repo.head({"src/lib.ts": lib.replace("    return;\n  }\n}", "    return void 0;\n  }\n}")})
        m = self.repo.build()
        arrow = m.arrow(box_id("src/lib.ts", "go"), box_id("src/lib.ts", "Impl.run"))
        self.assertIsNotNone(arrow)
        self.assertEqual(arrow["certainty"], "possible")
        self.assertIn("Base.run", arrow["reason"])

    def test_structural_match_only_when_assignable(self):  # [pr-map AC-6] [pr-map AC-7]
        lib = (
            "export interface Task {\n  run(): void;\n  size: number;\n}\n"
            "export class Shaped {\n  size = 1;\n  run(): void {\n    return;\n  }\n}\n"
            "export class Runner {\n  run(a: string, b: number): number {\n    return b;\n  }\n}\n"
            "export function go(t: Task): void {\n  t.run();\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib}))
        changed = lib.replace("    return;\n  }\n}", "    return void 0;\n  }\n}").replace("return b;", "return b + 1;")
        self.repo.head({"src/lib.ts": changed})
        m = self.repo.build()
        go = box_id("src/lib.ts", "go")
        self.assertEqual(m.certainty(go, box_id("src/lib.ts", "Shaped.run")), "possible")
        self.assertIsNone(m.arrow(go, box_id("src/lib.ts", "Runner.run")), "Runner is not assignable to Task")

    def test_data_property_with_a_function_name_draws_no_arrow(self):  # [pr-map AC-7]
        lib = (
            "export function notes(): number[] {\n  return [];\n}\n"
            "export interface Clip {\n  notes: number[];\n}\n"
            "export function count(c: Clip): number {\n  return c.notes.length;\n}\n"
            "export function make(notes: number[]): Clip {\n  return { notes };\n}\n"
            "export function fresh(): number[] {\n  return notes();\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib}))
        self.repo.head({"src/lib.ts": lib.replace("return [];", "return [0];")})
        m = self.repo.build()
        target = box_id("src/lib.ts", "notes")
        self.assertEqual(m.certainty(box_id("src/lib.ts", "fresh"), target), "exact", "positive control")
        self.assertIsNone(m.arrow(box_id("src/lib.ts", "count"), target))
        self.assertIsNone(m.arrow(box_id("src/lib.ts", "make"), target))

    def test_constructors_super_and_new_this(self):  # [pr-map AC-4] [pr-map AC-5] [pr-map AC-7]
        lib = (
            "export class Foo {\n  constructor(public n: number) {}\n"
            "  static make(): Foo {\n    return new this(1);\n  }\n}\n"
            "export class Baz extends Foo {\n  constructor() {\n    super(2);\n  }\n}\n"
            "export class Plain extends Foo {}\n"
        )
        use = (
            'import { Foo, Plain } from "./lib.js";\n'
            "export function build(): Foo {\n  return new Foo(1);\n}\n"
            "export function sub(): Plain {\n  return new Plain(3);\n}\n"
            "export function typed(f: Foo): number {\n  return f.n;\n}\n"
            "export function viaStatic(): Foo {\n  return Foo.make();\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib, "src/use.ts": use}))
        new_ctor = "constructor(public n: number) {\n    this.n = n;\n  }"
        changed = (
            lib.replace("constructor(public n: number) {}", new_ctor)
            .replace("super(2);", "super(3);")
            .replace("return new this(1);", "return new this(2);")
        )
        self.repo.head({"src/lib.ts": changed})
        m = self.repo.build()
        ctor = box_id("src/lib.ts", "Foo.constructor")
        self.assertEqual(m.certainty(box_id("src/use.ts", "build"), ctor), "exact")
        self.assertEqual(m.certainty(box_id("src/use.ts", "sub"), ctor), "exact", "Plain has no constructor")
        self.assertEqual(m.certainty(box_id("src/lib.ts", "Baz.constructor"), ctor), "exact", "super(3)")
        self.assertEqual(m.certainty(box_id("src/lib.ts", "Foo.make"), ctor), "exact", "new this(2)")
        self.assertIsNone(m.arrow(box_id("src/use.ts", "typed"), ctor), "a type annotation is not a call")
        self.assertIsNone(m.arrow(box_id("src/use.ts", "viaStatic"), ctor), "Foo.make() is not a constructor call")
        self.assertEqual(len(m.arrows(box_id("src/use.ts", "build"))), 1, "new Foo(1) is one arrow")

    def test_overloaded_call_resolves_to_the_one_box(self):  # [pr-map AC-5]
        lib = (
            "export function ov(x: number): number;\n"
            "export function ov(x: string): string;\n"
            "export function ov(x: number | string): number | string {\n  return x;\n}\n"
            "export function use(): number {\n  return ov(1);\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib}))
        self.repo.head({"src/lib.ts": lib.replace("  return x;", "  return x ?? 0;")})
        m = self.repo.build()
        self.assertEqual(m.certainty(box_id("src/lib.ts", "use"), box_id("src/lib.ts", "ov")), "exact")

    def test_parameter_on_the_name_line_is_not_the_function(self):  # [pr-map AC-5] [pr-map AC-7]
        lib = (
            "export function apply(cb: () => number): number {\n  return cb();\n}\n"
            "export function callIt(): number {\n  return apply(() => 1);\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib}))
        self.repo.head({"src/lib.ts": lib.replace("return cb();", "return cb() + 1;")})
        m = self.repo.build()
        target = box_id("src/lib.ts", "apply")
        self.assertEqual(m.certainty(box_id("src/lib.ts", "callIt"), target), "exact", "positive control")
        self.assertIsNone(m.arrow(target, target))

    def test_library_calls_draw_no_arrow(self):  # [pr-map AC-7] [pr-map AC-11]
        lib = "export function action(): number {\n  return 1;\n}\n"
        use = (
            'import { Command } from "commander";\n'
            "export function wire(): void {\n"
            "  new Command().action(() => {});\n"
            "  const program = new Command();\n"
            "  program.action(() => {});\n"
            "}\n"
            "export function typed(cmd: Command): void {\n  cmd.action(() => {});\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib, "src/use.ts": use}))
        self.repo.head({"src/lib.ts": lib.replace("return 1;", "return 2;")})
        m = self.repo.build()
        target = box_id("src/lib.ts", "action")
        self.assertEqual(m.arrows(target=target), [], "commander is not installed, and is not the repository")
        self.assertIn("library call", m.comment.lower())

    def test_unresolved_relative_import_is_possible(self):  # [pr-map AC-6]
        lib = "export function gone(): number {\n  return 1;\n}\n"
        use = 'import { gone } from "./missing.js";\nexport function caller(): number {\n  return gone();\n}\n'
        self.repo.base(self.project({"src/lib.ts": lib, "src/use.ts": use}))
        self.repo.head({"src/lib.ts": lib.replace("return 1;", "return 2;")})
        m = self.repo.build()
        arrow = m.arrow(box_id("src/use.ts", "caller"), box_id("src/lib.ts", "gone"))
        self.assertIsNotNone(arrow)
        self.assertEqual(arrow["certainty"], "possible")
        self.assertIn("unresolved", arrow["reason"])

    def test_removed_class_used_only_in_types(self):  # [pr-map AC-3]
        lib = "export class Rec {\n  id = 1;\n}\nexport class Keep {\n  id = 2;\n}\n"
        use = 'import type { Rec } from "./lib.js";\nexport function show(r: Rec): number {\n  return 1;\n}\n'
        self.repo.base(self.project({"src/lib.ts": lib, "src/use.ts": use}))
        self.repo.head({"src/lib.ts": "export class Keep {\n  id = 2;\n}\n"})
        m = self.repo.build()
        self.assertEqual(m.status("src/lib.ts", "Rec"), "removed")
        self.assertEqual(m.certainty(box_id("src/use.ts", "show"), box_id("src/lib.ts", "Rec")), "possible")

    def test_every_arrow_matches_a_listed_reference(self):  # [pr-map AC-7]
        lib = (
            "export interface Base {\n  run(): void;\n}\n"
            "export class Impl implements Base {\n  run(): void {\n    return;\n  }\n}\n"
            "export function run(): number {\n  return 9;\n}\n"
            "export function go(b: Base, x: { run(): void }): number {\n  b.run();\n  x.run();\n  return run();\n}\n"
        )
        self.repo.base(self.project({"src/lib.ts": lib}))
        self.repo.head({"src/lib.ts": lib.replace("    return;\n", "    return void 0;\n")})
        m = self.repo.build()
        self.assertTrue(m.arrows(target=box_id("src/lib.ts", "Impl.run")))
        m.check_against(
            self,
            {
                self.repo.site("src/lib.ts", "  b.run();"): UNCERTAIN,
                self.repo.site("src/lib.ts", "  x.run();"): UNCERTAIN,
                self.repo.site("src/lib.ts", "class Impl implements Base"): UNCERTAIN,
            },
        )


if __name__ == "__main__":
    unittest.main()
