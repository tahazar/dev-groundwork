"""Find the functions, methods and classes in a source file, and the identifiers that may refer to them.

Design: docs/specs/pr-map/design.md, Pipeline steps 2 and 4 and the data
model. tree-sitter parses each file, and the tags-style queries in queries/
find definitions and reference sites (research.md C19 to C21, C26). A file
with syntax errors still yields the constructs that parse (C8, C11), and its
error lines are kept so the comment can name it (AC-19).

tree-sitter reports columns in bytes; everything here is converted to
characters, the unit of Box.column.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Query, QueryCursor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from groundwork_config import walk_files

QUERIES = Path(__file__).resolve().parent / "queries"

# Extension -> (grammar, query file). TSX has its own grammar, a superset of TypeScript's.
LANGUAGES = {
    ".py": (tree_sitter_python.language, "python.scm"),
    ".ts": (tree_sitter_typescript.language_typescript, "typescript.scm"),
    ".tsx": (tree_sitter_typescript.language_tsx, "typescript.scm"),
}

# Query capture kind -> construct kind. An interface holds members the way a class does.
KINDS = {"function": "function", "method": "method", "class": "class", "interface": "class", "member": "member"}

# Declarations with no body. Adjacent same-name ones form one construct with the
# implementation that follows them: TypeScript overloads (design, step 6).
SIGNATURES = {"function_signature", "method_signature", "abstract_method_signature"}

# Wrappers whose span belongs to the definition they wrap, so a changed decorator
# or `export` keyword changes the construct.
WRAPPERS = {"decorated_definition", "export_statement"}


class UnreadableSource(ValueError):
    """A source file that cannot be decoded, so its columns cannot be converted."""


@dataclass(frozen=True)
class Construct:
    """A function, method, class or member as the source declares it.

    The map's Box is made from this; the span and nesting are what
    classification needs and the Box does not carry.
    """

    id: str  # "<path>::<qualified name>", plus "#2", "#3" for repeats in one file
    kind: str  # "function" | "method" | "class" | "member"
    name: str  # qualified: "Class.method", "outer.inner"
    path: str
    line: int  # 1-based line of the (first) name
    column: int  # 0-based character column of the (first) name
    names: tuple[tuple[int, int], ...]  # every name position: overloads have one per signature
    start_line: int  # 1-based, including decorators and `export`
    end_line: int  # 1-based, inclusive
    parent: str | None  # id of the innermost construct around this one


@dataclass(frozen=True)
class Site:
    """An identifier that may refer to a construct: a candidate reference (design, step 5)."""

    name: str
    line: int  # 1-based
    column: int  # 0-based character column
    call: bool  # the callee of a call or `new` (including TypeScript `super(...)` and `new this(...)`)
    owner: str | None  # id of the innermost construct containing it; None at module level


@dataclass(frozen=True)
class FileConstructs:
    path: str
    constructs: tuple[Construct, ...]  # in source order
    sites: tuple[Site, ...]  # in source order
    error_lines: tuple[int, ...]  # 1-based lines of syntax errors; empty when the file parses cleanly


def supported(path: str) -> bool:
    return Path(path).suffix in LANGUAGES


@cache
def _grammar(suffix: str) -> tuple[Parser, Query]:
    language_fn, query_file = LANGUAGES[suffix]
    language = Language(language_fn())
    return Parser(language), Query(language, (QUERIES / query_file).read_text(encoding="utf-8"))


def char_column(line: bytes, byte_column: int) -> int:
    """Characters before byte_column in a UTF-8 line."""
    return len(line[:byte_column].decode("utf-8"))


def parse(path: str, source: bytes) -> FileConstructs:
    """Constructs, reference sites and syntax-error lines of one file.

    path is relative to the repository root, and its suffix picks the
    grammar. Raises UnreadableSource when source is not UTF-8.
    """
    try:
        source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnreadableSource(f"{path} is not UTF-8 text: {exc}") from exc
    parser, query = _grammar(Path(path).suffix)
    tree = parser.parse(source)
    lines = source.split(b"\n")

    def position(node: Node) -> tuple[int, int]:
        row, byte_column = node.start_point
        return row + 1, char_column(lines[row], byte_column)

    definitions: list[tuple[Node, Node, str]] = []  # (definition node, name node, query kind)
    calls: set[int] = set()
    references: dict[int, Node] = {}
    for _, captures in QueryCursor(query).matches(tree.root_node):
        for capture, nodes in captures.items():
            if capture.startswith("definition."):
                definitions.append((nodes[0], captures["name"][0], capture.removeprefix("definition.")))
            elif capture.startswith("reference."):
                for node in nodes:
                    references[node.start_byte] = node
                    if capture == "reference.call":
                        calls.add(node.start_byte)
    definitions.sort(key=lambda d: d[0].start_byte)

    # Group overload signatures with each other and with the implementation that follows.
    groups: list[list[tuple[Node, Node, str]]] = []
    for definition in definitions:
        node, name, _ = definition
        previous = groups[-1][-1] if groups else None
        if (
            previous is not None
            and previous[0].type in SIGNATURES
            and _next_declaration(_span(previous[0])) == _span(node)
            and previous[1].text == name.text
        ):
            groups[-1].append(definition)
        else:
            groups.append([definition])

    node_group: dict[int, int] = {}  # definition node id -> index in groups
    for index, group in enumerate(groups):
        for node, _, _ in group:
            node_group[node.id] = index

    def enclosing(node: Node) -> int | None:
        """Index of the innermost group whose span contains node, excluding node's own group."""
        own = node_group.get(node.id)
        current = node.parent
        while current is not None:
            index = node_group.get(current.id)
            if index is None and current.type in WRAPPERS:
                inner = current.child_by_field_name("definition") or current.child_by_field_name("declaration")
                index = node_group.get(inner.id) if inner is not None else None
            if index is not None and index != own:
                return index
            current = current.parent
        return None

    parents = [enclosing(group[0][0]) for group in groups]
    qualified: list[str] = []
    for index, group in enumerate(groups):
        node, name, _ = group[0]
        prefix = qualified[parents[index]] + "." if parents[index] is not None else ""
        holder = _object_holder(node)
        if holder is not None:
            prefix += holder + "."
        qualified.append(prefix + name.text.decode("utf-8"))

    ids: list[str] = []
    seen: dict[str, int] = {}
    for name in qualified:
        seen[name] = seen.get(name, 0) + 1
        ids.append(f"{path}::{name}" + (f"#{seen[name]}" if seen[name] > 1 else ""))

    constructs = []
    for index, group in enumerate(groups):
        kind = KINDS[group[-1][2]]
        parent = parents[index]
        if kind == "function" and parent is not None and KINDS[groups[parent][-1][2]] == "class":
            kind = "method"  # a Python function directly inside a class
        names = tuple(position(name) for _, name, _ in group)
        constructs.append(
            Construct(
                id=ids[index],
                kind=kind,
                name=qualified[index],
                path=path,
                line=names[0][0],
                column=names[0][1],
                names=names,
                start_line=_span(group[0][0]).start_point[0] + 1,
                end_line=group[-1][0].end_point[0] + 1,
                parent=ids[parents[index]] if parents[index] is not None else None,
            )
        )

    name_starts = {name.start_byte for group in groups for _, name, _ in group}
    sites = []
    for start in sorted(references):
        if start in name_starts:
            continue
        node = references[start]
        owner = enclosing(node)
        line, column = position(node)
        sites.append(
            Site(
                name=node.text.decode("utf-8"),
                line=line,
                column=column,
                call=start in calls,
                owner=ids[owner] if owner is not None else None,
            )
        )

    return FileConstructs(path, tuple(constructs), tuple(sites), _error_lines(tree.root_node))


def scan(root: Path) -> tuple[dict[str, FileConstructs], dict[str, str]]:
    """Parse every supported file under root, outside the skip list (design, step 2).

    Returns the parsed files and, separately, the files that could not be
    read with the reason, both keyed by path relative to root.
    """
    parsed: dict[str, FileConstructs] = {}
    unreadable: dict[str, str] = {}
    for file in walk_files(root):
        rel = file.relative_to(root).as_posix()
        if not supported(rel):
            continue
        try:
            parsed[rel] = parse(rel, file.read_bytes())
        except (OSError, UnreadableSource) as exc:
            unreadable[rel] = str(exc)
    return parsed, unreadable


def _span(node: Node) -> Node:
    """The node whose lines belong to a definition: its decorator or export wrapper, if any."""
    parent = node.parent
    if parent is not None and parent.type in WRAPPERS:
        return parent
    return node


def _next_declaration(node: Node) -> Node | None:
    """The next named sibling that is not a comment."""
    following = node.next_named_sibling
    while following is not None and following.type == "comment":
        following = following.next_named_sibling
    return following


def _object_holder(node: Node) -> str | None:
    """For a method of an object literal held in a variable (`const fake = { run() {} }`), the variable's name."""
    parent = node.parent
    if node.type not in ("method_definition", "pair") or parent is None or parent.type != "object":
        return None
    holder = parent.parent
    if holder is None or holder.type != "variable_declarator" or holder.child_by_field_name("value") != parent:
        return None
    name = holder.child_by_field_name("name")
    return name.text.decode("utf-8") if name is not None and name.type == "identifier" else None


def _error_lines(root: Node) -> tuple[int, ...]:
    """1-based lines of ERROR and MISSING nodes (C8); only subtrees that contain an error are visited."""
    lines: set[int] = set()
    pending = [root] if root.has_error else []
    while pending:
        node = pending.pop()
        if node.is_error or node.is_missing:
            lines.add(node.start_point[0] + 1)
        pending.extend(child for child in node.children if child.has_error or child.is_missing)
    return tuple(sorted(lines))
