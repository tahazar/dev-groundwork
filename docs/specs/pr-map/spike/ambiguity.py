"""Spike: how often does a call's bare name match more than one definition in the repo?"""

import collections
import pathlib
import sys

import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser, Query, QueryCursor

root = pathlib.Path(sys.argv[1])
skip = ("node_modules", "dist", ".venv")
cfg = {
    ".ts": (
        Language(tsts.language_typescript()),
        """
(function_declaration name: (identifier) @def)
(method_definition name: (property_identifier) @def)
(class_declaration name: (type_identifier) @def)
(variable_declarator name: (identifier) @def value: [(arrow_function) (function_expression)])
(call_expression function: [(identifier) @ref (member_expression property: (property_identifier) @ref)])""",
    ),
    ".py": (
        Language(tspy.language()),
        """
(function_definition name: (identifier) @def)
(class_definition name: (identifier) @def)
(call function: [(identifier) @ref (attribute attribute: (identifier) @ref)])""",
    ),
}
for ext, (lang, q) in cfg.items():
    defs = collections.Counter()
    refs = []
    p = Parser(lang)
    query = Query(lang, q)
    for f in root.rglob("*" + ext):
        if any(s in f.parts for s in skip):
            continue
        caps = QueryCursor(query).captures(p.parse(f.read_bytes()).root_node)
        defs.update(n.text.decode() for n in caps.get("def", []))
        refs += [n.text.decode() for n in caps.get("ref", [])]
    to_repo = [r for r in refs if defs[r] >= 1]
    ambiguous = [r for r in to_repo if defs[r] > 1]
    dup = sorted((n for n, c in defs.items() if c > 1), key=lambda n: -defs[n])[:8]
    print(
        f"{ext}: calls whose name matches a repo definition={len(to_repo)}, "
        f"of which match 2+ definitions={len(ambiguous)} ({100 * len(ambiguous) / max(1, len(to_repo)):.0f}%); "
        f"most-duplicated names: {[(n, defs[n]) for n in dup]}"
    )
