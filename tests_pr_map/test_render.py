"""The comment body: header, diagrams, splitting, text list and notes (AC-8, AC-10 to AC-13, AC-17, AC-19)."""

from __future__ import annotations

import re
import unittest

from helpers import box_id, render

render_comment = render.render_comment

RUN_URL = "https://github.com/o/r/actions/runs/7"


def box(path: str, name: str, status: str = "neighbour", line: int = 1) -> dict:
    return {
        "id": box_id(path, name),
        "kind": "function",
        "name": name,
        "path": path,
        "line": line,
        "column": 4,
        "status": status,
    }


def arrow(source: dict, target: dict, certainty: str = "exact", reason: str = "", line: int = 9) -> dict:
    return {
        "source": source["id"],
        "target": target["id"],
        "certainty": certainty,
        "at": f"{source['path']}:{line}:5",
        "reason": reason,
    }


def a_map(boxes: list[dict], arrows: list[dict], notes: dict | None = None) -> dict:
    return {"base": "1111111aaaa", "head": "2222222bbbb", "boxes": boxes, "arrows": arrows, "notes": notes or {}}


def diagrams(comment: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", comment, re.DOTALL)


def star(n: int) -> dict:
    """One changed box called by n distinct callers."""
    target = box("lib.py", "hub", "changed")
    callers = [box(f"pkg/m{i}.py", f"caller{i}") for i in range(n)]
    return a_map([target, *callers], [arrow(c, target) for c in callers])


class RenderTests(unittest.TestCase):
    def test_header_names_base_and_head_commits(self):  # [pr-map AC-17]
        comment = render_comment(star(1), RUN_URL)
        self.assertIn("1111111", comment)
        self.assertIn("2222222", comment)

    def test_empty_map_says_nothing_to_map(self):  # [pr-map AC-10]
        comment = render_comment(a_map([], []), RUN_URL)
        self.assertIn("No function-level changes to map", comment)
        self.assertEqual(diagrams(comment), [])

    def test_box_label_has_name_and_path_with_line(self):  # [pr-map AC-8]
        target = box("pkg/lib.py", "Clip.render", "changed", line=42)
        caller = box("pkg/use.py", "main", line=3)
        comment = render_comment(a_map([target, caller], [arrow(caller, target)]), RUN_URL)
        parts = diagrams(comment)
        self.assertEqual(len(parts), 1)
        diagram = parts[0]
        self.assertIn("Clip.render", diagram)
        self.assertIn("pkg/lib.py:42", diagram)

    def test_status_is_written_in_the_label_not_only_coloured(self):  # [pr-map AC-8]
        target = box("lib.py", "edit", "changed")
        added = box("lib.py", "fresh", "added")
        removed = box("lib.py", "gone", "removed")
        comment = render_comment(a_map([target, added, removed], []), RUN_URL)
        for word in ("changed", "added", "removed"):
            self.assertIn(word, "".join(diagrams(comment)))

    def test_exact_and_possible_arrows_look_different(self):  # [pr-map AC-6]
        target = box("lib.py", "run", "changed")
        a, b = box("a.py", "a"), box("b.py", "b")
        comment = render_comment(
            a_map([target, a, b], [arrow(a, target), arrow(b, target, "possible", "through Base.run")]), RUN_URL
        )
        parts = diagrams(comment)
        self.assertEqual(len(parts), 1)
        diagram = parts[0]
        self.assertRegex(diagram, r"-->")
        self.assertRegex(diagram, r"-\.->\|possible\|")

    def test_small_map_is_one_diagram(self):  # [pr-map AC-12]
        self.assertEqual(len(diagrams(render_comment(star(20), RUN_URL))), 1)

    def test_large_map_splits_and_keeps_every_box_and_arrow(self):  # [pr-map AC-11] [pr-map AC-12]
        m = star(600)
        comment = render_comment(m, RUN_URL)
        parts = diagrams(comment)
        self.assertGreater(len(parts), 1, "600 arrows exceed the 450-arrow budget")
        for part in parts:
            self.assertLessEqual(len(part), 45_000)
            self.assertLessEqual(part.count("-->") + part.count("-.->"), 450)
        joined = "".join(parts)
        for b in m["boxes"]:
            self.assertIn(b["name"], joined, f"box missing from every diagram: {b['name']}")
        arrow_count = sum(p.count("-->") + p.count("-.->") for p in parts)
        self.assertGreaterEqual(arrow_count, 600, "every arrow is drawn in at least one diagram")

    def test_budget_is_configurable_for_the_split(self):  # [pr-map AC-12]
        parts = diagrams(render_comment(star(30), RUN_URL, max_arrows=10))
        self.assertGreaterEqual(len(parts), 3)
        for part in parts:
            self.assertLessEqual(part.count("-->") + part.count("-.->"), 10)

    def test_text_list_has_every_arrow_in_a_collapsed_section(self):  # [pr-map AC-13]
        m = star(5)
        comment = render_comment(m, RUN_URL)
        details = re.search(r"<details>(.*?)</details>", comment, re.DOTALL)
        self.assertIsNotNone(details)
        for a in m["arrows"]:
            self.assertIn(a["at"].rsplit(":", 1)[0], details.group(1))
        for i in range(5):
            self.assertIn(f"caller{i}", details.group(1))

    def test_notes_name_skipped_files_and_syntax_errors(self):  # [pr-map AC-19]
        notes = {
            "skipped": [{"path": "bad.py", "reason": "not UTF-8"}],
            "syntax_errors": [{"path": "half.py", "lines": [5]}],
        }
        comment = render_comment(a_map([box("lib.py", "edit", "changed")], [], notes), RUN_URL)
        self.assertIn("bad.py", comment)
        self.assertIn("not UTF-8", comment)
        self.assertIn("half.py", comment)
        self.assertIn("5", comment)


if __name__ == "__main__":
    unittest.main()
