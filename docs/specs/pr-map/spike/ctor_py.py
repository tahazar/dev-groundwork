"""Spike: constructor references and an uninstalled library with jedi."""

import pathlib
import sys

import jedi

root = pathlib.Path(sys.argv[1]).resolve()
project = jedi.Project(root)
lib = (root / "lib.py").read_text()
refs = jedi.Script(lib, path=root / "lib.py", project=project).get_references(2, 8, scope="project")
print("jedi get_references Foo.__init__:", [(r.module_path.name, r.line, r.column) for r in refs])
use = (root / "use.py").read_text()
lines = use.splitlines()
for needle in ("Foo(1)", "np.mean"):
    line = next(i for i, text in enumerate(lines, 1) if needle in text)
    column = lines[line - 1].index(needle) + (3 if needle == "np.mean" else 0)
    found = jedi.Script(use, path=root / "use.py", project=project).goto(line, column, follow_imports=True)
    print(
        f"jedi goto {needle}:",
        [(d.module_path.name if d.module_path else None, d.line, d.column, d.type) for d in found],
    )
