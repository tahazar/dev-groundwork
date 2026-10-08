"""Render a map as the pull request comment: header, Mermaid diagrams, text list and notes.

Design: docs/specs/pr-map/design.md, Pipeline step 8. The input is the
JSON-ready map from pr_map.build_map: base, head, boxes, arrows and notes.
"""

from __future__ import annotations

import html
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple

# Mermaid's defaults are 50,000 characters and 500 edges per diagram (C27, C28), and GitHub states no
# limit of its own (C29), so each diagram stays under these, with room to spare.
MAX_CHARS = 45_000
MAX_ARROWS = 450

NOTHING = "No function-level changes to map"
STATUSES = ("changed", "added", "removed")
# A class adds colour; the status is also written in the label, so it does not depend on colour.
COLOURS = {
    "changed": "fill:#fff8c5,stroke:#9a6700",
    "added": "fill:#dafbe1,stroke:#1a7f37",
    "removed": "fill:#ffebe9,stroke:#cf222e",
}
# Characters written as Mermaid entity codes (`#<decimal>;`) inside a quoted label: `"` would end the
# label, `#` would start an entity, `<`, `>` and `&` would read as HTML, and the rest as markdown, which
# Mermaid 11 applies to labels (`__init__` showed as a bold "init"). Measured with mermaid 11.4.1 in
# Chromium: entity codes survive the markdown pass only when the label's lines are split by a newline,
# not `<br>`, so labels use a newline.
MERMAID_ESCAPES = {c: f"#{ord(c)};" for c in '#"<>&`_*~[]\\'}

log = logging.getLogger("pr_map")


class Edge(NamedTuple):
    """One line in a diagram: the arrows from source to target with one certainty, drawn once."""

    source: str
    target: str
    certainty: str


class Diagram(NamedTuple):
    title: str  # empty for the one diagram of a map that fits
    boxes: list[dict]
    edges: list[Edge]


def render_comment(pr_map: dict, run_url: str, max_chars: int = MAX_CHARS, max_arrows: int = MAX_ARROWS) -> str:
    """Return the comment body for a map produced by pr_map.build_map.

    run_url, when not empty, is linked as the workflow run that built the map.
    """
    return comment_versions(pr_map, run_url, max_chars, max_arrows)[0]


def comment_versions(pr_map: dict, run_url: str, max_chars: int = MAX_CHARS, max_arrows: int = MAX_ARROWS) -> list[str]:
    """The comment body, then ever smaller versions for when GitHub rejects it as too long (design, step 9).

    The comment length limit is undocumented (C30), so the poster tries these
    in order. After the complete body: the text list moved out, then the
    diagrams moved out, last first, one per version; each says what moved and
    links run_url. The last version is the header, the counts and the link.
    """
    boxes = pr_map["boxes"]
    arrows = pr_map["arrows"]
    notes = pr_map.get("notes", {})
    by_id = {b["id"]: b for b in boxes}
    for a in arrows:
        for end in (a["source"], a["target"]):
            if end not in by_id:
                raise ValueError(f"rendering the map: arrow at {a['at']} names box {end!r}, which is not in the map")
    header = ["### Function map", "", f"Computed from `{pr_map['base'][:7]}` (base) to `{pr_map['head'][:7]}` (head)."]
    if run_url:
        header[-1] += f" Built by [this workflow run]({run_url})."
    header.append("")
    where = f"[the workflow run's summary]({run_url})" if run_url else "the workflow run's summary"
    if not any(b["status"] in STATUSES for b in boxes):
        listed = _notes(notes)
        whole = [*header, NOTHING + ".", "", *listed]
        if not listed:
            return ["\n".join(whole)]
        brief = [*header, NOTHING + ".", "", f"Notes moved to {where}: the comment was too long."]
        return ["\n".join(whole), "\n".join(brief)]
    counts = [_counts(boxes, arrows), ""]
    legend = [
        "Solid arrows are references the language's own tooling resolved to that exact definition; "
        "dashed `possible` arrows are references it could not rule out.",
        "",
    ]
    ids = {b["id"]: f"b{i}" for i, b in enumerate(boxes)}

    def fits(part_boxes: list[dict], edges: list[Edge]) -> bool:
        return len(edges) <= max_arrows and len(mermaid(part_boxes, edges, ids)) <= max_chars

    drawn = []
    for d in split(boxes, edges_of(arrows), fits):
        drawn.append(
            ([f"**{d.title}**", ""] if d.title else []) + ["```mermaid", mermaid(d.boxes, d.edges, ids) + "```", ""]
        )

    def version(kept: int, moved: str) -> str:
        out = [*header, *counts]
        if moved:
            out += [f"**Shortened:** the comment was too long, so {moved} moved to {where}.", ""]
        out += legend
        for lines in drawn[:kept]:
            out += lines
        out += _notes(notes)
        if not moved:
            out += _text_list(boxes, arrows, notes, by_id)
        return "\n".join(out)

    n = len(drawn)
    versions = [version(n, ""), version(n, "the text list")]
    for kept in range(n - 1, -1, -1):
        versions.append(version(kept, f"the text list and {n - kept} of {n} diagram{'s' if n != 1 else ''}"))
    versions.append(
        "\n".join([*header, *counts, f"**Shortened:** the comment was too long, so the map moved to {where}."])
    )
    return versions


def edges_of(arrows: list[dict]) -> list[Edge]:
    """One edge per source, target and certainty, in the arrows' order; the text list keeps every site."""
    return list(dict.fromkeys(Edge(a["source"], a["target"], a["certainty"]) for a in arrows))


def split(boxes: list[dict], edges: list[Edge], fits: Callable[[list[dict], list[Edge]], bool]) -> list[Diagram]:
    """Diagrams that each fit, with every box and edge in at least one (design, step 8, Splitting).

    The whole map if it fits; else one diagram per connected group of boxes;
    a group over budget becomes one diagram per changed, added or removed box
    with its edges; a box over budget splits its edges into numbered parts.
    """
    if fits(boxes, edges):
        return [Diagram("", boxes, edges)]
    by_id = {b["id"]: b for b in boxes}
    groups = _groups(boxes, edges)
    result = []
    for number, (members, inner) in enumerate(groups, 1):
        title = f"Group {number} of {len(groups)}"
        if fits(members, inner):
            result.append(Diagram(title, members, inner))
            continue
        for anchor, own in _by_box(members, inner, by_id):
            name = f"{title}: {_label(anchor)}"
            parts = _parts(anchor, own, members, fits)
            if len(parts) == 1:
                result.append(Diagram(name, *parts[0]))
            else:
                result += [Diagram(f"{name}, part {k} of {len(parts)}", *p) for k, p in enumerate(parts, 1)]
    return result


def mermaid(boxes: list[dict], edges: list[Edge], ids: dict[str, str]) -> str:
    """One `flowchart LR` with a line per box, per edge and per status class, ending in a newline."""
    lines = ["flowchart LR"]
    classes: dict[str, list[str]] = defaultdict(list)
    for b in boxes:
        status = f"{b['status']}: " if b["status"] in STATUSES else ""
        text = f"{escape(status + b['name'])}\n{escape(b['path'])}:{b['line']}"
        lines.append(f'  {ids[b["id"]]}["{text}"]')
        if b["status"] in STATUSES:
            classes[b["status"]].append(ids[b["id"]])
    for e in edges:
        link = "-->" if e.certainty == "exact" else "-.->|possible|"
        lines.append(f"  {ids[e.source]} {link} {ids[e.target]}")
    for status in STATUSES:
        if classes[status]:
            lines += [f"  classDef {status} {COLOURS[status]}", f"  class {','.join(classes[status])} {status}"]
    return "\n".join(lines) + "\n"


def escape(text: str) -> str:
    """Text safe inside a quoted Mermaid label: the characters in MERMAID_ESCAPES as entity codes."""
    return "".join(MERMAID_ESCAPES.get(c, c) for c in text)


def _groups(boxes: list[dict], edges: list[Edge]) -> list[tuple[list[dict], list[Edge]]]:
    """Connected groups of boxes, each with its edges, in the order of their first box."""
    parent = {b["id"]: b["id"] for b in boxes}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[root(e.source)] = root(e.target)
    members: dict[str, list[dict]] = defaultdict(list)
    for b in boxes:
        members[root(b["id"])].append(b)
    inner: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        inner[root(e.source)].append(e)
    return [(group, inner[key]) for key, group in members.items()]


def _by_box(members: list[dict], edges: list[Edge], by_id: dict[str, dict]) -> list[tuple[dict, list[Edge]]]:
    """Each changed, added or removed box with the edges touching it.

    An edge touching none of them (two neighbours) goes with its source, so
    no edge is left out.
    """
    own: dict[str, list[Edge]] = {b["id"]: [] for b in members if b["status"] in STATUSES}
    for e in edges:
        touched = [end for end in (e.source, e.target) if end in own]
        for end in dict.fromkeys(touched):
            own[end].append(e)
        if not touched:
            own.setdefault(e.source, []).append(e)
    return [(by_id[key], found) for key, found in own.items()]


def _parts(
    anchor: dict, edges: list[Edge], boxes: list[dict], fits: Callable[[list[dict], list[Edge]], bool]
) -> list[tuple[list[dict], list[Edge]]]:
    """The anchor's edges cut into consecutive parts that each fit with the boxes they reach.

    The smallest part is the anchor alone, or with one edge. When even that is
    over budget (a label longer than the character budget), it is still drawn,
    so the box and edge are not lost, and a warning is logged: GitHub may then
    not render that one diagram, and the text list still has the arrow.
    """

    def reach(part: list[Edge]) -> list[dict]:
        ends = {anchor["id"]} | {e.source for e in part} | {e.target for e in part}
        return [b for b in boxes if b["id"] in ends]

    parts: list[list[Edge]] = []
    current: list[Edge] = []
    for e in edges:
        if current and not fits(reach([*current, e]), [*current, e]):
            parts.append(current)
            current = []
        current.append(e)
    parts.append(current)
    for part in parts:
        if not fits(reach(part), part):
            log.warning("a diagram for %s is over the Mermaid budget even alone; drawing it anyway", anchor["id"])
    return [(reach(part), part) for part in parts]


def _label(b: dict) -> str:
    return f"{_code(b['name'])} ({_code(b['path'] + ':' + str(b['line']))})"


def _counts(boxes: list[dict], arrows: list[dict]) -> str:
    status = defaultdict(int)
    for b in boxes:
        status[b["status"]] += 1
    exact = sum(a["certainty"] == "exact" for a in arrows)
    return (
        f"{status['changed']} changed, {status['added']} added, {status['removed']} removed, "
        f"{status['neighbour']} neighbours; {len(arrows)} arrows ({exact} exact, {len(arrows) - exact} possible)."
    )


def _notes(notes: dict) -> list[str]:
    """The notes a reviewer must see next to the diagrams: what could not be read or resolved."""
    out = []
    if notes.get("skipped"):
        out += ["**Skipped files** (could not be read, so not mapped):"]
        out += [f"- {_code(s['path'])}: {_text(s['reason'])}" for s in notes["skipped"]]
        out.append("")
    if notes.get("syntax_errors"):
        out += ["**Files with syntax errors** (mapped from the parts that parse):"]
        for s in notes["syntax_errors"]:
            lines = ", ".join(str(n) for n in s["lines"])
            out.append(f"- {_code(s['path'])}: syntax error on line{'s' if len(s['lines']) > 1 else ''} {lines}")
        out.append("")
    if notes.get("typescript_fallback"):
        out += [
            f"**TypeScript resolver unavailable:** {_text(notes['typescript_fallback'])}. "
            "TypeScript references are drawn as possible arrows.",
            "",
        ]
    if notes.get("resolver_failures"):
        out += ["**Resolver failures** (the references found by name are drawn as possible arrows):"]
        out += [f"- {_code(_site(f['at']))}: {_text(f['reason'])}" for f in notes["resolver_failures"]]
        out.append("")
    return out


def _text_list(boxes: list[dict], arrows: list[dict], notes: dict, by_id: dict[str, dict]) -> list[str]:
    """The collapsed text list: every arrow, every box without arrows, and what was found but not drawn."""
    linked = {a["source"] for a in arrows} | {a["target"] for a in arrows}
    alone = [b for b in boxes if b["id"] not in linked]
    unresolved = notes.get("unresolved", [])
    summary = f"Text list: {len(arrows)} arrows, {len(alone)} boxes without arrows, {len(unresolved)} unresolved calls"
    out = ["<details>", f"<summary>{summary}</summary>", ""]
    if arrows:
        out += ["| From | To | Arrow | Call site |", "|---|---|---|---|"]
        for a in arrows:
            kind = (
                "exact"
                if a["certainty"] == "exact"
                else "possible" + (f" ({_text(a['reason'])})" if a["reason"] else "")
            )
            source, target = by_id[a["source"]], by_id[a["target"]]
            out.append(
                f"| {_cell(_label(source))} | {_cell(_label(target))} | {_cell(kind)} | {_code(_site(a['at']))} |"
            )
        out.append("")
    if alone:
        out += ["Boxes without arrows:"]
        out += [f"- {b['status']}: {_label(b)}" for b in alone]
        out.append("")
    if unresolved:
        out += ["Unresolved calls (not drawn: more than one repository definition has the name):"]
        for u in unresolved:
            n = len(u["options"])
            out.append(
                f"- {_code(u['name'])} at {_code(_site(u['at']))} in {_code(_who(u['source'], by_id))}: "
                f"{n} possible repository target{'s' if n != 1 else ''}"
            )
        out.append("")
    if notes.get("removed_constructor_calls"):
        out += ["Calls of a class whose constructor was removed (they may now pass the wrong arguments):"]
        for c in notes["removed_constructor_calls"]:
            cls, _, method = _who(c["target"], by_id).rpartition(".")
            out.append(
                f"- {_code(_site(c['at']))} in {_code(_who(c['source'], by_id))}: "
                f"called {_code(cls + '(…)')}, whose {_code(method)} was removed"
            )
        out.append("")
    if notes.get("refers"):
        out += ["References to definitions that are not boxes (no arrow drawn):"]
        for r in notes["refers"]:
            out.append(
                f"- {_code(r['name'])} at {_code(_site(r['at']))} in {_code(_who(r['source'], by_id))} "
                f"refers to {_code(r['refers_to'])}"
            )
        out.append("")
    if notes.get("library_calls"):
        out += ["Library calls (not drawn: the library is not part of the repository):"]
        for c in notes["library_calls"]:
            out.append(f"- {_code(c['path'])}: {c['count']} library call{'s' if c['count'] != 1 else ''}")
        out.append("")
    out.append("</details>")
    return out


def _who(box_id: str, by_id: dict[str, dict]) -> str:
    """A box's name, or the name part of an id the map has no box for."""
    return by_id[box_id]["name"] if box_id in by_id else box_id.partition("::")[2] or box_id


def _site(at: str) -> str:
    """`path:line` of a `path:line:column` reference site."""
    return at.rsplit(":", 1)[0]


def _code(text: str) -> str:
    """A markdown code span; a longer fence when the text holds a backtick."""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _cell(text: str) -> str:
    """Text for a markdown table cell, where `|` ends the cell even inside a code span."""
    return text.replace("|", "\\|")


def _text(text: str) -> str:
    """Free text (a parser's or resolver's reason) on one line, with `<`, `>` and `&` escaped so it is not read as HTML.

    A multi-line reason (a TypeScript error) would end a table row or a list item, so its lines are joined.
    """
    return html.escape(" ".join(str(text).split()), quote=False)
