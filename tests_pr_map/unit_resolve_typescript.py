"""Tests for resolve.py on TypeScript: the Node helper resolve_ts.cjs, its protocol, its fallback, and the
TypeScript rows of the verdict table, on small temporary repositories with the pinned compiler.

Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'
(needs `npm ci --prefix scripts/pr_map`)
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import resolve
from resolve import CALLEE, CALLER, REMOVED, Answer, Candidate, Code, Verdict
from unit_resolve_python import Repo

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


class TsRepo(Repo):
    """A Repo whose resolver's helper is stopped after the test, with Code.implements filled in."""

    def __init__(self, testcase: unittest.TestCase, files: dict[str, str], removed: dict[str, str] | None = None):
        super().__init__(testcase, files, removed)
        testcase.addCleanup(self.resolver.close)
        live = [c for c in self.code.constructs.values() if c.id in self.code.positions.values()]
        implements = {c.id: self.resolver.structural(c, live) for c in live if c.kind == "method"}
        self.code = Code(self.code.constructs, self.code.positions, self.code.bases, implements)

    def candidate(self, rel: str, needle: str, role: str, target: str | None = None, name: str | None = None, **kw):
        s = self.site(rel, needle, name)
        return Candidate(rel, s.line, s.column, s.name, s.call, role, target, **kw)

    def judge_candidate(self, candidate: Candidate) -> Verdict:
        answer = Answer(
            tuple(self.resolver.definition_at(candidate.path, candidate.line, candidate.column)),
            traced=self.resolver.trace_import(candidate.path, candidate.line, candidate.column),
        )
        named = [c.id for c in self.code.constructs.values() if c.name.rsplit(".", 1)[-1] == candidate.name]
        return resolve.verdict(candidate, answer, self.code, [n for n in named if n in self.code.positions.values()])


def project(files: dict[str, str]) -> dict[str, str]:
    return {"tsconfig.json": TSCONFIG, **files}


class DefinitionTests(unittest.TestCase):
    def test_call_resolves_to_the_function_name_position(self):
        lib = "export function target(): number {\n  return 1;\n}\n"
        use = 'import { target } from "./lib.js";\nexport function caller(): number {\n  return target();\n}\n'
        repo = TsRepo(self, project({"src/lib.ts": lib, "src/use.ts": use}))
        s = repo.site("src/use.ts", "target()")
        [loc] = repo.resolver.definition_at("src/use.ts", s.line, s.column)
        self.assertEqual(
            (loc.path, loc.line, loc.column, loc.kind, loc.local), ("src/lib.ts", 1, 16, "function", False)
        )
        self.assertEqual(
            repo.judge("src/use.ts", "target()", CALLER, "src/lib.ts::target"), Verdict("exact", "src/lib.ts::target")
        )
        self.assertEqual(repo.resolver.typescript_failure, "")

    def test_columns_are_utf16_on_the_wire_and_characters_in_locations(self):
        # "😀" is one character but two UTF-16 code units, and "é" one of each.
        lib = "/* é😀 */ export function target(): number {\n  return 1;\n}\n"
        use = (
            'import { target } from "./lib.js";\n'
            'export function caller(): [string, number] {\n  return ["é😀😀", target()];\n}\n'
        )
        repo = TsRepo(self, project({"src/lib.ts": lib, "src/use.ts": use}))
        s = repo.site("src/use.ts", "target()")
        self.assertEqual(s.column, use.splitlines()[2].index("target"), "a character column")
        [loc] = repo.resolver.definition_at("src/use.ts", s.line, s.column)
        self.assertEqual((loc.path, loc.line, loc.column), ("src/lib.ts", 1, lib.index("target")))
        self.assertEqual(
            repo.judge("src/use.ts", "target()", CALLER, "src/lib.ts::target"), Verdict("exact", "src/lib.ts::target")
        )

    def test_workspace_package_resolves_to_its_source_without_a_build(self):
        files = {
            "packages/core/package.json": package("@x/core"),
            "packages/core/tsconfig.json": TSCONFIG,
            "packages/core/src/index.ts": "export function parse(s: string): number {\n  return s.length;\n}\n",
            "packages/cli/package.json": package("@x/cli"),
            "packages/cli/tsconfig.json": TSCONFIG,
            "packages/cli/src/index.ts": (
                'import { parse } from "@x/core";\nexport function run(): number {\n  return parse("a");\n}\n'
            ),
        }
        repo = TsRepo(self, files)
        v = repo.judge("packages/cli/src/index.ts", 'parse("a")', CALLER, "packages/core/src/index.ts::parse")
        self.assertEqual(v, Verdict("exact", "packages/core/src/index.ts::parse"), "no dist/ exists (C38 to C40)")
        s = repo.site("packages/cli/src/index.ts", 'parse("a")')
        self.assertEqual(repo.resolver.trace_import("packages/cli/src/index.ts", s.line, s.column), "repository")

    def test_the_projects_own_paths_win_over_the_workspace_mapping(self):
        own = json.loads(TSCONFIG)
        own["compilerOptions"]["paths"] = {"@x/*": ["./src/shim.ts"]}
        files = {
            "packages/core/package.json": package("@x/core"),
            "packages/core/tsconfig.json": TSCONFIG,
            "packages/core/src/index.ts": "export function parse(s: string): number {\n  return s.length;\n}\n",
            "packages/cli/package.json": package("@x/cli"),
            "packages/cli/tsconfig.json": json.dumps(own),
            "packages/cli/src/shim.ts": "export function parse(s: string): number {\n  return 0;\n}\n",
            "packages/cli/src/index.ts": (
                'import { parse } from "@x/core";\nexport function run(): number {\n  return parse("a");\n}\n'
            ),
        }
        repo = TsRepo(self, files)
        s = repo.site("packages/cli/src/index.ts", 'parse("a")')
        [loc] = repo.resolver.definition_at("packages/cli/src/index.ts", s.line, s.column)
        self.assertEqual(loc.path, "packages/cli/src/shim.ts")

    def test_file_outside_the_tsconfig_include_is_added_to_the_project(self):
        lib = "export function total(xs: number[]): number {\n  return xs.length;\n}\n"
        test = 'import { total } from "../src/lib.js";\nexport function checks(): number {\n  return total([1]);\n}\n'
        repo = TsRepo(self, project({"src/lib.ts": lib, "test/lib.test.ts": test}))
        v = repo.judge("test/lib.test.ts", "total([1])", CALLER, "src/lib.ts::total")
        self.assertEqual(v, Verdict("exact", "src/lib.ts::total"))
        found = repo.resolver.references("src/lib.ts", 1, 16)
        self.assertIn(("test/lib.test.ts", 3, 9), [(loc.path, loc.line, loc.column) for loc in found])

    def test_no_tsconfig_uses_default_options(self):
        lib = "export function target(): number {\n  return 1;\n}\n"
        use = 'import { target } from "./lib";\nexport function caller(): number {\n  return target();\n}\n'
        repo = TsRepo(self, {"lib.ts": lib, "use.ts": use})
        self.assertEqual(repo.judge("use.ts", "target()", CALLER, "lib.ts::target"), Verdict("exact", "lib.ts::target"))

    def test_parameter_and_local_const_are_local_and_the_standard_library_is_outside(self):
        lib = "export function apply(cb: () => number): number {\n  const n = Math.max(1, 2);\n  return cb() + n;\n}\n"
        repo = TsRepo(self, project({"src/lib.ts": lib}))
        [param] = repo.resolver.definition_at("src/lib.ts", 3, 9)
        [const] = repo.resolver.definition_at("src/lib.ts", 3, 16)
        [library] = repo.resolver.definition_at("src/lib.ts", 2, 17)
        self.assertTrue(param.local)
        self.assertTrue(const.local)
        self.assertIsNone(library.path, library)
        self.assertEqual(repo.judge("src/lib.ts", "cb()", CALLEE), Verdict(""))
        self.assertEqual(repo.judge("src/lib.ts", "Math.max", CALLEE, name="max"), Verdict(""))

    def test_references_follow_a_renamed_import_and_leave_out_the_definition(self):
        lib = "export function readClip(): number {\n  return 1;\n}\n"
        use = 'import { readClip as rc } from "./lib.js";\nexport function a(): number {\n  return rc();\n}\n'
        repo = TsRepo(self, project({"src/lib.ts": lib, "src/use.ts": use}))
        found = [(loc.path, loc.line, loc.column, loc.name) for loc in repo.resolver.references("src/lib.ts", 1, 16)]
        self.assertIn(("src/use.ts", 3, 9, "rc"), found, "C43")
        self.assertNotIn(("src/lib.ts", 1, 16, "readClip"), found)

    def test_bad_position_raises_resolver_error_naming_the_site(self):
        repo = TsRepo(self, project({"src/lib.ts": "export const x = 1;\n"}))
        with self.assertRaisesRegex(resolve.ResolverError, r"reading src/lib\.ts:9 for the resolver"):
            repo.resolver.definition_at("src/lib.ts", 9, 0)
        with self.assertRaisesRegex(resolve.ResolverError, r"TypeScript definition: definition at src/lib\.ts:1:"):
            repo.resolver._helper().ask({"op": "definition", "file": "src/lib.ts", "line": 1, "column": 400})
        self.assertEqual(repo.resolver.typescript_failure, "", "an error answer is not a helper failure")


class VerdictTests(unittest.TestCase):
    def test_overloaded_call_is_the_one_box(self):
        lib = (
            "export function ov(x: number): number;\n"
            "export function ov(x: string): string;\n"
            "export function ov(x: number | string): number | string {\n  return x;\n}\n"
            "export function use(): number {\n  return ov(1);\n}\n"
        )
        repo = TsRepo(self, project({"src/lib.ts": lib}))
        s = repo.site("src/lib.ts", "ov(1)")
        [loc] = repo.resolver.definition_at("src/lib.ts", s.line, s.column)
        self.assertEqual(loc.line, 1, "C55: the matching signature only")
        self.assertEqual(
            repo.judge("src/lib.ts", "ov(1)", CALLER, "src/lib.ts::ov"), Verdict("exact", "src/lib.ts::ov")
        )
        self.assertEqual(repo.judge("src/lib.ts", "ov(1)", CALLEE), Verdict("exact", "src/lib.ts::ov"))

    def test_call_through_an_implemented_interface_found_by_references_is_possible(self):
        lib = (
            "export interface Base {\n  run(): void;\n}\n"
            "export class Mid implements Base {\n  run(): void {}\n}\n"
            "export class Impl extends Mid {\n  run(): void {\n    return;\n  }\n}\n"
            "export function go(b: Base): void {\n  b.run();\n}\n"
        )
        repo = TsRepo(self, project({"src/lib.ts": lib}))
        found = repo.resolver.references("src/lib.ts", 8, 2)
        self.assertIn(("src/lib.ts", 13, 4), [(loc.path, loc.line, loc.column) for loc in found], "C45")
        candidate = repo.candidate("src/lib.ts", "b.run()", CALLER, "src/lib.ts::Impl.run", "run", referenced=True)
        v = repo.judge_candidate(candidate)
        self.assertEqual(v, Verdict("possible", "src/lib.ts::Impl.run", "through `src/lib.ts::Base.run`"))
        self.assertEqual(
            repo.judge("src/lib.ts", "b.run()", CALLEE, name="run"), Verdict("exact", "src/lib.ts::Base.run")
        )

    def test_structural_match_only_when_assignable_and_a_function(self):
        lib = (
            "export interface Task {\n  run(): void;\n  size: number;\n  stop: () => void;\n}\n"
            "export class Shaped {\n  size = 1;\n  run(): void {\n    return;\n  }\n  stop(): void {}\n}\n"
            "export class Runner {\n  run(a: string, b: number): number {\n    return b;\n  }\n}\n"
            "export class Sized {\n  size(): number {\n    return 1;\n  }\n}\n"
            "export function go(t: Task): void {\n  t.run();\n}\n"
        )
        repo = TsRepo(self, project({"src/lib.ts": lib}))
        implements = repo.code.implements
        self.assertEqual(implements["src/lib.ts::Shaped.run"], {"src/lib.ts::Task.run"})
        self.assertEqual(implements["src/lib.ts::Shaped.stop"], {"src/lib.ts::Task.stop"}, "a function-typed property")
        self.assertEqual(implements["src/lib.ts::Runner.run"], frozenset(), "C64: not assignable")
        self.assertEqual(implements["src/lib.ts::Sized.size"], frozenset(), "a data property is not related")
        v = repo.judge("src/lib.ts", "t.run()", CALLER, "src/lib.ts::Shaped.run", "run")
        self.assertEqual(v, Verdict("possible", "src/lib.ts::Shaped.run", "through `src/lib.ts::Task.run`"))
        self.assertEqual(repo.judge("src/lib.ts", "t.run()", CALLER, "src/lib.ts::Runner.run", "run"), Verdict(""))

    def test_data_property_with_a_function_name_draws_no_arrow(self):
        lib = (
            "export function notes(): number[] {\n  return [];\n}\n"
            "export interface Clip {\n  notes: number[];\n}\n"
            "export function count(c: Clip): number {\n  return c.notes.length;\n}\n"
        )
        repo = TsRepo(self, project({"src/lib.ts": lib}))
        self.assertEqual(repo.judge("src/lib.ts", "c.notes", CALLER, "src/lib.ts::notes", "notes"), Verdict(""))

    def test_library_calls_are_counted_not_drawn(self):
        lib = "export function action(): number {\n  return 1;\n}\n"
        use = (
            'import { Command } from "commander";\n'
            "export function wire(cmd: Command): void {\n"
            "  new Command().action(() => {});\n"
            "  const program = new Command();\n"
            "  program.action(() => {});\n"
            "  cmd.action(() => {});\n"
            "}\n"
        )
        repo = TsRepo(self, project({"src/lib.ts": lib, "src/use.ts": use}))
        for needle in ("Command().action", "program.action", "cmd.action"):
            v = repo.judge("src/use.ts", needle, CALLER, "src/lib.ts::action", "action")
            self.assertEqual(v, Verdict("", note="library"), needle)

    def test_variable_assigned_twice_is_not_traced(self):
        use = (
            'import { Command } from "commander";\n'
            "export function wire(other: { action(): void }): void {\n"
            "  let program = new Command();\n"
            "  program = other;\n"
            "  program.action();\n"
            "}\n"
        )
        repo = TsRepo(self, project({"src/use.ts": use}))
        s = repo.site("src/use.ts", "program.action", "action")
        self.assertEqual(repo.resolver.trace_import("src/use.ts", s.line, s.column), "")

    def test_unresolved_relative_import_is_possible(self):
        lib = "export function gone(): number {\n  return 1;\n}\n"
        use = 'import { gone } from "./missing.js";\nexport function caller(): number {\n  return gone();\n}\n'
        repo = TsRepo(self, project({"src/lib.ts": lib, "src/use.ts": use}))
        s = repo.site("src/use.ts", "gone()")
        [loc] = repo.resolver.definition_at("src/use.ts", s.line, s.column)
        self.assertEqual((loc.path, loc.line, loc.kind), ("src/use.ts", 1, "alias"), "the import line only")
        v = repo.judge("src/use.ts", "gone()", CALLER, "src/lib.ts::gone")
        self.assertEqual(v, Verdict("possible", "src/lib.ts::gone", "unresolved import"))


CONSTRUCTORS = (
    "export class Foo {\n  constructor(public n: number) {}\n"
    "  static make(): Foo {\n    return new this(1);\n  }\n}\n"
    "export class Baz extends Foo {\n  constructor() {\n    super(2);\n  }\n}\n"
    "export class Plain extends Foo {}\n"
    "export class Bare {}\n"
)
CONSTRUCTOR_USES = (
    'import { Bare, Foo, Plain } from "./lib.js";\n'
    "export function build(): Foo {\n  return new Foo(1);\n}\n"
    "export function sub(): Plain {\n  return new Plain(3);\n}\n"
    "export function typed(f: Foo): number {\n  return f.n;\n}\n"
    "export function viaStatic(): Foo {\n  return Foo.make();\n}\n"
    "export function bare(): Bare {\n  return new Bare();\n}\n"
)
CTOR = "src/lib.ts::Foo.constructor"


class ConstructorTests(unittest.TestCase):
    def setUp(self):
        self.repo = TsRepo(self, project({"src/lib.ts": CONSTRUCTORS, "src/use.ts": CONSTRUCTOR_USES}))

    def caller(self, rel: str, needle: str, target: str = CTOR, name: str | None = None) -> Verdict:
        return self.repo.judge(rel, needle, CALLER, target, name)

    def test_new_super_and_new_this_run_the_constructor(self):
        self.assertEqual(self.caller("src/use.ts", "Foo(1)"), Verdict("exact", CTOR), "C52")
        self.assertEqual(self.caller("src/use.ts", "Plain(3)"), Verdict("exact", CTOR), "no constructor of its own")
        self.assertEqual(self.caller("src/lib.ts", "super(2)"), Verdict("exact", CTOR), "C61")
        self.assertEqual(self.caller("src/lib.ts", "this(1)", name="this"), Verdict("exact", CTOR))

    def test_annotation_and_static_call_are_not_constructor_calls(self):
        self.assertEqual(self.caller("src/use.ts", "f: Foo", name="Foo"), Verdict(""))
        self.assertEqual(self.caller("src/use.ts", "Foo.make()", name="Foo"), Verdict(""))

    def test_class_target_counts_the_pair_and_the_class_alone(self):
        self.assertEqual(self.caller("src/use.ts", "Foo(1)", "src/lib.ts::Foo"), Verdict("exact", "src/lib.ts::Foo"))
        self.assertEqual(
            self.caller("src/use.ts", "f: Foo", "src/lib.ts::Foo", "Foo"), Verdict("exact", "src/lib.ts::Foo")
        )

    def test_callee_new_is_one_arrow_to_the_constructor_else_the_class(self):
        self.assertEqual(self.repo.judge("src/use.ts", "Foo(1)", CALLEE), Verdict("exact", CTOR))
        self.assertEqual(self.repo.judge("src/use.ts", "Bare()", CALLEE), Verdict("exact", "src/lib.ts::Bare"))

    def test_call_of_a_class_whose_constructor_was_removed_is_listed(self):
        repo = TsRepo(
            self,
            project(
                {"src/lib.ts": "export class Foo {}\n", "src/use.ts": 'import { Foo } from "./lib.js";\nnew Foo();\n'}
            ),
            removed={"src/lib.ts": "export class Foo {\n  constructor() {}\n}\n"},
        )
        v = repo.judge("src/use.ts", "Foo()", REMOVED, CTOR)
        self.assertEqual(v, Verdict("", target=CTOR, note="removed constructor"))


NEVER_ANSWERS = "process.stdin.on('data', () => {});\n"


class FallbackTests(unittest.TestCase):
    """The one fallback (design, step 7), in both directions."""

    def repo(self) -> TsRepo:
        lib = (
            "export function target(): number {\n  return 1;\n}\n"
            "export function caller(): number {\n  return target();\n}\n"
        )
        return TsRepo(self, project({"src/lib.ts": lib}))

    def scratch(self) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        return directory

    def assert_falls_back(self, repo: TsRepo, reason: str) -> resolve.ResolverError:
        s = repo.site("src/lib.ts", "return target()", "target")
        with self.assertLogs("pr_map", "WARNING") as logged:
            with self.assertRaisesRegex(resolve.ResolverError, "TypeScript resolver unavailable: " + reason) as caught:
                repo.resolver.definition_at("src/lib.ts", s.line, s.column)
        self.assertRegex(logged.output[0], "fall back to possible arrows: " + reason)
        self.assertRegex(repo.resolver.typescript_failure, reason)
        candidate = Candidate("src/lib.ts", s.line, s.column, "target", True, CALLER, "src/lib.ts::target")
        v = resolve.verdict(candidate, Answer(error=str(caught.exception)), repo.code)
        self.assertEqual((v.certainty, v.target), ("possible", "src/lib.ts::target"))
        self.assertRegex(v.reason, "^resolver failed: TypeScript resolver unavailable: " + reason)
        with self.assertNoLogs("pr_map", "WARNING"), self.assertRaisesRegex(resolve.ResolverError, reason):
            repo.resolver.trace_import("src/lib.ts", s.line, s.column)  # later requests fail fast, logged once
        return caught.exception

    def test_working_helper_answers_without_a_warning(self):
        repo = self.repo()
        s = repo.site("src/lib.ts", "return target()", "target")
        with self.assertNoLogs("pr_map", "WARNING"):
            v = repo.judge("src/lib.ts", "return target()", CALLER, "src/lib.ts::target", "target")
        self.assertEqual(v, Verdict("exact", "src/lib.ts::target"))
        self.assertEqual(repo.resolver.typescript_failure, "")
        self.assertTrue(repo.resolver.definition_at("src/lib.ts", s.line, s.column))

    def test_node_missing(self):
        repo = self.repo()
        repo.resolver.node = str(self.scratch() / "no-node")
        caught = self.assert_falls_back(repo, "Node could not be started")
        self.assertIsInstance(caught.__cause__, OSError, "the cause is kept")

    def test_helper_missing(self):
        repo = self.repo()
        repo.resolver._typescript = resolve.TypeScript(repo.root, [], helper=self.scratch() / "resolve_ts.cjs")
        self.assert_falls_back(repo, "the helper .*resolve_ts.cjs is missing")

    def test_typescript_package_missing(self):
        helper = self.scratch() / "resolve_ts.cjs"
        shutil.copy(resolve.HELPER, helper)  # no node_modules next to it
        repo = self.repo()
        repo.resolver._typescript = resolve.TypeScript(repo.root, [], helper=helper)
        self.assert_falls_back(
            repo, "the helper exited with code 1: Error: Cannot find module '.*/node_modules/typescript'"
        )

    def test_helper_dies(self):
        repo = self.repo()
        s = repo.site("src/lib.ts", "return target()", "target")
        repo.resolver.definition_at("src/lib.ts", s.line, s.column)
        repo.resolver._typescript._process.kill()
        repo.resolver._typescript._process.wait()
        self.assert_falls_back(repo, "the helper (exited with code -9|stopped reading requests)")

    def test_helper_that_does_not_answer_is_stopped(self):
        helper = self.scratch() / "resolve_ts.cjs"
        helper.write_text(NEVER_ANSWERS, encoding="utf-8")
        repo = self.repo()
        repo.resolver._typescript = resolve.TypeScript(repo.root, [], helper=helper, timeout=0.5)
        self.assert_falls_back(repo, "the helper gave no answer within 0.5 s")
        self.assertIsNotNone(repo.resolver._typescript._process.poll(), "the helper was stopped")


if __name__ == "__main__":
    unittest.main()
