"""Tests for render.py: escaping, the split order, the budget boundary and completeness across diagrams.

Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import render

NODE = re.compile(r'^  (b\d+)\["(.*)$')
EDGE = re.compile(r"^  (b\d+) (-->|-\.->\|possible\|) (b\d+)$")


def b(path: str, name: str, status: str = "neighbour", line: int = 1) -> dict:
    return {
        "id": f"{path}::{name}",
        "kind": "function",
        "name": name,
        "path": path,
        "line": line,
        "column": 0,
        "status": status,
    }


def arrow(source: dict, target: dict, certainty: str = "exact", line: int = 9, reason: str = "") -> dict:
    return {
        "source": source["id"],
        "target": target["id"],
        "certainty": certainty,
        "at": f"{source['path']}:{line}:4",
        "reason": reason,
    }


def a_map(boxes: list[dict], arrows: list[dict], notes: dict | None = None) -> dict:
    return {"base": "a" * 40, "head": "c" * 40, "boxes": boxes, "arrows": arrows, "notes": notes or {}}


def star(name: str, n: int, status: str = "changed") -> tuple[list[dict], list[dict]]:
    hub = b(f"{name}.py", name, status)
    callers = [b(f"{name}/c{i}.py", f"{name}_c{i}") for i in range(n)]
    return [hub, *callers], [arrow(c, hub) for c in callers]


def blocks(comment: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", comment, re.DOTALL)


def titles(comment: str) -> list[str]:
    return re.findall(r"^\*\*(.*)\*\*$", comment, re.MULTILINE)


def parsed(diagram: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    """The node ids and (source, target, certainty) edges a diagram draws."""
    nodes, edges = set(), set()
    for line in diagram.splitlines():
        if m := NODE.match(line):
            nodes.add(m.group(1))
        elif m := EDGE.match(line):
            edges.add((m.group(1), m.group(3), "exact" if m.group(2) == "-->" else "possible"))
    return nodes, edges


class Covered(unittest.TestCase):
    def assert_complete(self, m: dict, comment: str) -> None:
        """Every box and every arrow (as an edge) is drawn in at least one diagram, and nothing else is."""
        ids = {x["id"]: f"b{i}" for i, x in enumerate(m["boxes"])}
        nodes, edges = set(), set()
        for d in blocks(comment):
            found_nodes, found_edges = parsed(d)
            for s, t, _ in found_edges:
                self.assertIn(s, found_nodes, "an edge's ends are drawn in its own diagram")
                self.assertIn(t, found_nodes)
            nodes |= found_nodes
            edges |= found_edges
        self.assertEqual(nodes, set(ids.values()))
        self.assertEqual(edges, {(ids[a["source"]], ids[a["target"]], a["certainty"]) for a in m["arrows"]})


class EscapeTests(unittest.TestCase):
    def test_label_characters_become_entity_codes(self):
        self.assertEqual(render.escape('say "hi"'), "say #34;hi#34;")
        self.assertEqual(render.escape("a#b"), "a#35;b")
        self.assertEqual(render.escape("x<y>&z"), "x#60;y#62;#38;z")
        self.assertEqual(render.escape("C.__init__"), "C.#95;#95;init#95;#95;")
        self.assertEqual(render.escape("a[0]*~`\\"), "a#91;0#93;#42;#126;#96;#92;")

    def test_entity_text_is_not_read_as_an_entity(self):
        self.assertEqual(render.escape("#quot;"), "#35;quot;")

    def test_non_ascii_and_mermaid_words_pass_through(self):
        self.assertEqual(render.escape("Ünïcode.函数"), "Ünïcode.函数")
        self.assertEqual(render.escape("end"), "end")

    def test_label_holds_status_name_and_path_line_on_two_lines(self):
        x = b("p/a b.py", 'q"[x]', "added", line=7)
        text = render.mermaid([x], [], {x["id"]: "b0"})
        self.assertIn('  b0["added: q#34;#91;x#93;\np/a b.py:7"]', text)
        self.assertIn("class b0 added", text)

    def test_neighbour_label_has_no_status_and_no_class(self):
        x = b("a.py", "n")
        text = render.mermaid([x], [], {x["id"]: "b0"})
        self.assertIn('b0["n\na.py:1"]', text)
        self.assertNotIn("class ", text)

    def test_ids_are_generated_so_names_cannot_break_the_syntax(self):
        hub = b("lib.py", "-->", "changed")
        caller = b("x.py", 'a"] --> b0["', "neighbour")
        comment = render.render_comment(a_map([hub, caller], [arrow(caller, hub)]), "")
        (d,) = blocks(comment)
        self.assertEqual(d.count("-->"), 1, "names never add an arrow token")
        self.assertIn("  b1 --> b0\n", d)

    def test_text_list_escapes_table_cells(self):
        hub = b("lib.py", "a|b", "changed")
        caller = b("x.py", "c")
        comment = render.render_comment(a_map([hub, caller], [arrow(caller, hub)]), "")
        self.assertIn("`a\\|b`", comment)

    def test_free_text_reasons_are_not_html(self):
        notes = {"skipped": [{"path": "bad.py", "reason": "byte <0xff> & more"}]}
        comment = render.render_comment(a_map([b("lib.py", "f", "changed")], [], notes), "")
        self.assertIn("byte &lt;0xff&gt; &amp; more", comment)

    def test_a_multi_line_reason_stays_in_its_table_row(self):
        hub, caller = b("lib.py", "hub", "changed"), b("use.py", "use")
        m = a_map([hub, caller], [arrow(caller, hub, "possible", reason="resolver failed: TS2304\n  at x.ts")])
        comment = render.render_comment(m, "")
        self.assertIn("| possible (resolver failed: TS2304 at x.ts) | `use.py:9` |", comment)


class SplitOrderTests(Covered):
    def test_a_map_that_fits_is_one_untitled_diagram(self):
        boxes, arrows = star("hub", 5)
        m = a_map(boxes, arrows)
        comment = render.render_comment(m, "")
        self.assertEqual(len(blocks(comment)), 1)
        self.assertEqual(titles(comment), [])
        self.assertIn("flowchart LR\n", blocks(comment)[0])

    def test_over_budget_splits_into_connected_groups_first(self):
        one, one_arrows = star("one", 3)
        two, two_arrows = star("two", 3)
        lone = b("lone.py", "lone", "added")
        m = a_map([*one, *two, lone], one_arrows + two_arrows)
        comment = render.render_comment(m, "", max_arrows=5)
        self.assertEqual(titles(comment), ["Group 1 of 3", "Group 2 of 3", "Group 3 of 3"])
        self.assertEqual([len(parsed(d)[1]) for d in blocks(comment)], [3, 3, 0])
        self.assert_complete(m, comment)

    def test_a_group_over_budget_splits_per_changed_box(self):
        hub_a = b("a.py", "a", "changed")
        hub_b = b("b.py", "b", "removed")
        callers = [b(f"c{i}.py", f"c{i}") for i in range(4)]
        arrows = [arrow(c, hub_a) for c in callers] + [arrow(c, hub_b, "possible") for c in callers[:2]]
        m = a_map([hub_a, hub_b, *callers], arrows)
        comment = render.render_comment(m, "", max_arrows=5)
        self.assertEqual(titles(comment), ["Group 1 of 1: `a` (`a.py:1`)", "Group 1 of 1: `b` (`b.py:1`)"])
        self.assertEqual([len(parsed(d)[1]) for d in blocks(comment)], [4, 2])
        self.assert_complete(m, comment)

    def test_an_edge_between_two_changed_boxes_is_drawn_with_each(self):
        x, y = b("x.py", "x", "changed"), b("y.py", "y", "added")
        others = [b(f"o{i}.py", f"o{i}") for i in range(3)]
        m = a_map([x, y, *others], [arrow(x, y)] + [arrow(o, x) for o in others])
        comment = render.render_comment(m, "", max_arrows=3)
        edge = ("b0", "b1", "exact")
        self.assertEqual(sum(edge in parsed(d)[1] for d in blocks(comment)), 2)
        self.assert_complete(m, comment)

    def test_a_box_over_budget_splits_into_numbered_parts(self):
        boxes, arrows = star("hub", 7)
        m = a_map(boxes, arrows)
        comment = render.render_comment(m, "", max_arrows=3)
        self.assertEqual(
            titles(comment),
            [f"Group 1 of 1: `hub` (`hub.py:1`), part {k} of 3" for k in (1, 2, 3)],
        )
        self.assertEqual([len(parsed(d)[1]) for d in blocks(comment)], [3, 3, 1])
        self.assert_complete(m, comment)

    def test_repeated_sites_between_two_boxes_are_one_edge(self):
        hub, caller = b("lib.py", "hub", "changed"), b("use.py", "use")
        m = a_map([hub, caller], [arrow(caller, hub, line=3), arrow(caller, hub, line=4)])
        comment = render.render_comment(m, "", max_arrows=1)
        self.assertEqual(len(blocks(comment)), 1, "one edge fits a one-arrow budget")
        self.assertIn("`use.py:3`", comment)
        self.assertIn("`use.py:4`", comment, "the text list keeps every site")


class BudgetBoundaryTests(Covered):
    def test_exactly_at_the_arrow_budget_is_one_diagram(self):
        boxes, arrows = star("hub", 10)
        self.assertEqual(len(blocks(render.render_comment(a_map(boxes, arrows), "", max_arrows=10))), 1)

    def test_one_over_the_arrow_budget_splits(self):
        boxes, arrows = star("hub", 11)
        m = a_map(boxes, arrows)
        comment = render.render_comment(m, "", max_arrows=10)
        self.assertEqual([len(parsed(d)[1]) for d in blocks(comment)], [10, 1])
        self.assert_complete(m, comment)

    def test_exactly_at_the_character_budget_is_one_diagram(self):
        boxes, arrows = star("hub", 10)
        m = a_map(boxes, arrows)
        (whole,) = blocks(render.render_comment(m, ""))
        self.assertEqual(blocks(render.render_comment(m, "", max_chars=len(whole))), [whole])

    def test_one_over_the_character_budget_splits(self):
        boxes, arrows = star("hub", 10)
        m = a_map(boxes, arrows)
        (whole,) = blocks(render.render_comment(m, ""))
        comment = render.render_comment(m, "", max_chars=len(whole) - 1)
        parts = blocks(comment)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), len(whole) - 1)
        self.assert_complete(m, comment)


class CompletenessTests(Covered):
    def test_every_box_and_arrow_survives_a_mixed_split(self):
        one, one_arrows = star("one", 40)
        two, two_arrows = star("two", 6, "added")
        gone = b("gone.py", "gone", "removed")
        tail = [b(f"t{i}.py", f"t{i}") for i in range(5)]
        tail_arrows = [arrow(t, gone, "possible", reason="unresolved") for t in tail]
        callee = b("leaf.py", "leaf")
        m = a_map([*one, *two, gone, *tail, callee], one_arrows + two_arrows + tail_arrows + [arrow(one[0], callee)])
        for max_arrows in (1, 2, 7, 13, 50):
            with self.subTest(max_arrows=max_arrows):
                comment = render.render_comment(m, "", max_arrows=max_arrows)
                for d in blocks(comment):
                    self.assertLessEqual(len(parsed(d)[1]), max_arrows)
                self.assert_complete(m, comment)

    def test_an_edge_between_two_neighbours_goes_with_its_source(self):
        boxes, arrows = star("hub", 3)
        n1, n2 = boxes[1], boxes[2]
        m = a_map(boxes, [*arrows, arrow(n1, n2)])
        comment = render.render_comment(m, "", max_arrows=2)
        self.assertIn(f"Group 1 of 1: `{n1['name']}` (`{n1['path']}:1`)", titles(comment))
        self.assert_complete(m, comment)

    def test_a_part_over_the_character_budget_alone_is_still_drawn_with_a_warning(self):
        # The fallback in _parts: one box and one edge longer than the budget are drawn anyway.
        boxes, arrows = star("hub", 3)
        m = a_map(boxes, arrows)
        with self.assertLogs("pr_map", "WARNING") as logs:
            comment = render.render_comment(m, "", max_chars=10)
        self.assertEqual(len(blocks(comment)), 3)
        self.assertIn("over the Mermaid budget", logs.output[0])
        self.assert_complete(m, comment)

    def test_no_warning_when_every_part_fits(self):
        boxes, arrows = star("hub", 3)
        with self.assertNoLogs("pr_map", "WARNING"):
            render.render_comment(a_map(boxes, arrows), "", max_arrows=1)


class CommentTests(unittest.TestCase):
    def test_header_has_short_shas_and_the_run_link(self):
        comment = render.render_comment(a_map([b("lib.py", "f", "changed")], []), "https://example.test/run/1")
        self.assertIn("Computed from `aaaaaaa` (base) to `ccccccc` (head).", comment)
        self.assertIn("[this workflow run](https://example.test/run/1)", comment)

    def test_no_run_link_without_a_run_url(self):
        self.assertNotIn("workflow run", render.render_comment(a_map([b("lib.py", "f", "changed")], []), ""))

    def test_only_neighbours_is_nothing_to_map_but_keeps_the_notes(self):
        notes = {"skipped": [{"path": "bad.py", "reason": "not UTF-8"}]}
        comment = render.render_comment(a_map([], [], notes), "")
        self.assertIn(render.NOTHING, comment)
        self.assertIn("`bad.py`: not UTF-8", comment)
        self.assertEqual(blocks(comment), [])

    def test_text_list_rows_and_boxes_without_arrows(self):
        hub, caller, alone = b("lib.py", "hub", "changed", 4), b("use.py", "use", line=2), b("x.py", "x", "added")
        m = a_map([hub, caller, alone], [arrow(caller, hub, "possible", 6, "through `Base.hub`")])
        comment = render.render_comment(m, "")
        self.assertIn(
            "| `use` (`use.py:2`) | `hub` (`lib.py:4`) | possible (through `Base.hub`) | `use.py:6` |", comment
        )
        self.assertIn("- added: `x` (`x.py:1`)", comment)
        self.assertRegex(comment, r"(?s)<details>.*use\.py:6.*</details>")

    def test_notes_from_the_graph_are_listed(self):
        init = b("lib.py", "Foo.__init__", "removed", 2)
        user = b("use.py", "build")
        notes = {
            "unresolved": [
                {"at": "lib.py:8:4", "source": init["id"], "name": "get", "reason": "unresolved", "options": ["a", "b"]}
            ],
            "removed_constructor_calls": [{"at": "use.py:5:11", "source": user["id"], "target": init["id"]}],
            "refers": [
                {"at": "lib.py:10:20", "source": "lib.py::Clip.count", "name": "notes", "refers_to": "lib.py:7"}
            ],
            "library_calls": [{"path": "use.py", "count": 2}],
            "resolver_failures": [{"at": "lib.py:1:4", "reason": "jedi stopped"}],
            "typescript_fallback": "node not found",
            "syntax_errors": [{"path": "half.py", "lines": [5, 9]}],
        }
        comment = render.render_comment(a_map([init, user], [], notes), "")
        self.assertIn("- `get` at `lib.py:8` in `Foo.__init__`: 2 possible repository targets", comment)
        self.assertIn("- `use.py:5` in `build`: called `Foo(…)`, whose `__init__` was removed", comment)
        self.assertIn("- `notes` at `lib.py:10` in `Clip.count` refers to `lib.py:7`", comment)
        self.assertIn("- `use.py`: 2 library calls", comment)
        self.assertIn("- `lib.py:1`: jedi stopped", comment)
        self.assertIn("node not found", comment)
        self.assertIn("- `half.py`: syntax error on lines 5, 9", comment)

    def test_an_arrow_to_a_box_not_in_the_map_is_a_specific_error(self):
        hub = b("lib.py", "hub", "changed")
        stray = arrow(b("use.py", "use"), hub)
        with self.assertRaisesRegex(ValueError, "arrow at use.py:9:4 names box 'use.py::use'"):
            render.render_comment(a_map([hub], [stray]), "")


if __name__ == "__main__":
    unittest.main()
