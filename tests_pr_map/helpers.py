"""Shared fixtures for the pr-map acceptance tests.

A MapRepo is a throwaway git repository with a `base` branch and a head
commit on `main`; `build()` runs pr_map against it and returns the map.
References are written by hand per fixture: each reference site with the
box it really refers to, or UNCERTAIN where the code itself does not decide.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "pr_map"))
sys.path.insert(0, str(ROOT / "tests"))

import pr_map  # noqa: E402
import render  # noqa: E402  (re-exported for the tests)
from test_scripts import Repo, git  # noqa: E402

__all__ = ["UNCERTAIN", "Map", "MapRepo", "box_id", "pr_map", "render"]

UNCERTAIN = "uncertain"


def box_id(path: str, name: str) -> str:
    return f"{path}::{name}"


class MapRepo(Repo):
    """Commit `base` files on a `base` branch, then `head` changes on `main`."""

    def base(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            self.write(rel, text)
        self.commit("base")
        git(self.root, "branch", "base")

    def head(self, files: dict[str, str | None]) -> None:
        for rel, text in files.items():
            if text is None:
                (self.root / rel).unlink()
            else:
                self.write(rel, text)
        self.commit("head")

    def build(self) -> Map:
        with tempfile.TemporaryDirectory() as out:
            code = pr_map.main(["--base", "base", "--out", out])
            data = json.loads((Path(out) / "pr-map.json").read_text(encoding="utf-8"))
            comment = (Path(out) / "pr-map.md").read_text(encoding="utf-8")
        return Map(code, data, comment, self)

    def site(self, rel: str, needle: str, occurrence: int = 1) -> str:
        """`path:line` of the occurrence-th line containing needle in the head commit."""
        lines = (self.root / rel).read_text(encoding="utf-8").splitlines()
        hits = [i for i, text in enumerate(lines, 1) if needle in text]
        return f"{rel}:{hits[occurrence - 1]}"


@dataclass
class Map:
    code: int
    data: dict
    comment: str
    repo: MapRepo

    def box(self, path: str, name: str) -> dict | None:
        wanted = box_id(path, name)
        return next((b for b in self.data["boxes"] if b["id"] == wanted), None)

    def status(self, path: str, name: str) -> str | None:
        found = self.box(path, name)
        return found["status"] if found else None

    def arrows(self, source: str | None = None, target: str | None = None) -> list[dict]:
        return [
            a
            for a in self.data["arrows"]
            if (source is None or a["source"] == source) and (target is None or a["target"] == target)
        ]

    def arrow(self, source: str, target: str) -> dict | None:
        found = self.arrows(source, target)
        return found[0] if found else None

    def certainty(self, source: str, target: str) -> str | None:
        """'exact' or 'possible' for the arrow from source to target, or None when there is none."""
        found = self.arrow(source, target)
        return found["certainty"] if found else None

    def check_against(self, testcase, references: dict[str, str]) -> None:
        """AC-7: every arrow must sit at a hand-listed reference site.

        references maps `path:line` to the box id really referred to there,
        or UNCERTAIN. An exact arrow must match its site's true target; a
        possible arrow must match it, or sit at an UNCERTAIN site.
        """
        for a in self.data["arrows"]:
            site = ":".join(a["at"].split(":")[:2])
            testcase.assertIn(site, references, f"arrow at an unlisted site: {a}")
            truth = references[site]
            if a["certainty"] == "exact":
                testcase.assertEqual(truth, a["target"], f"exact arrow to the wrong box: {a}")
            else:
                testcase.assertIn(truth, (a["target"], UNCERTAIN), f"possible arrow to an unrelated box: {a}")
