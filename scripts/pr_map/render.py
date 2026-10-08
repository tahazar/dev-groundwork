"""Render a map as the pull request comment: header, Mermaid diagrams, text list and notes.

Stub until implementation task 8; see docs/specs/pr-map/design.md, Pipeline step 8.
"""

from __future__ import annotations

MAX_CHARS = 45_000
MAX_ARROWS = 450


def render_comment(pr_map: dict, run_url: str, max_chars: int = MAX_CHARS, max_arrows: int = MAX_ARROWS) -> str:
    """Return the comment body for a map produced by pr_map.build_map."""
    return ""
