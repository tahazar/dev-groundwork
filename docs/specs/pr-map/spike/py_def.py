"""Spike: go-to-definition with jedi for calls that share a name."""

import pathlib
import sys

import jedi

root = pathlib.Path(sys.argv[1]).resolve()
project = jedi.Project(root)
for arg in sys.argv[2:]:
    rel, line, needle = arg.split(":")
    f = root / rel
    src = f.read_text()
    col = src.splitlines()[int(line) - 1].index(needle)
    found = jedi.Script(src, path=f, project=project).goto(int(line), col, follow_imports=True)
    where = [f"{d.module_path.relative_to(root)}:{d.line}" for d in found]
    print(f"{needle} at {rel}:{line} -> {where}")
