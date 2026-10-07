"""Spike: parse a repo's TS and Python files with tree-sitter; count definitions, errors, time."""

import pathlib
import sys
import time

import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser, Query, QueryCursor

root = pathlib.Path(sys.argv[1])
TS = Language(tsts.language_typescript())
TSX = Language(tsts.language_tsx())
PY = Language(tspy.language())
ts_q = """
(function_declaration name: (identifier) @name) @definition.function
(method_definition name: (property_identifier) @name) @definition.method
(class_declaration name: (type_identifier) @name) @definition.class
(lexical_declaration
  (variable_declarator name: (identifier) @name value: [(arrow_function) (function_expression)])) @definition.function
(call_expression
  function: [(identifier) @name (member_expression property: (property_identifier) @name)]) @reference.call
"""
py_q = """
(function_definition name: (identifier) @name) @definition.function
(class_definition name: (identifier) @name) @definition.class
(call function: [(identifier) @name (attribute attribute: (identifier) @name)]) @reference.call
"""


def run(lang, q, files):
    p = Parser(lang)
    query = Query(lang, q)
    defs = refs = errs = 0
    t = time.perf_counter()
    for f in files:
        tree = p.parse(f.read_bytes())
        if tree.root_node.has_error:
            errs += 1
        caps = QueryCursor(query).captures(tree.root_node)
        defs += sum(len(v) for k, v in caps.items() if k.startswith("definition"))
        refs += sum(len(v) for k, v in caps.items() if k.startswith("reference"))
    return len(files), defs, refs, errs, time.perf_counter() - t


skip = ("node_modules", "dist", ".venv")
ts_files = [f for f in root.rglob("*.ts") if not any(s in f.parts for s in skip)]
tsx_files = [f for f in root.rglob("*.tsx") if not any(s in f.parts for s in skip)]
py_files = [f for f in root.rglob("*.py") if not any(s in f.parts for s in skip)]
for name, lang, q, fs in [("ts", TS, ts_q, ts_files), ("tsx", TSX, ts_q, tsx_files), ("py", PY, py_q, py_files)]:
    n, d, r, e, s = run(lang, q, fs)
    print(f"{name}: files={n} definitions={d} call-refs={r} files-with-parse-errors={e} seconds={s:.2f}")
# error tolerance: parse a deliberately broken snippet
p = Parser(TS)
tree = p.parse(b"function ok() { return 1 }\nfunction broken( { \nfunction after() { ok() }\n")
caps = QueryCursor(Query(TS, ts_q)).captures(tree.root_node)
print(
    "broken snippet: has_error",
    tree.root_node.has_error,
    "definitions found:",
    [n.text.decode() for n in caps.get("name", [])],
)
