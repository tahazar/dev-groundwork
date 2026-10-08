"""Spike: does jedi's get_references on a function include calls through a renamed import?"""

import pathlib
import sys

import jedi

root = pathlib.Path(sys.argv[1]).resolve()
src = (root / "report.py").read_text()
refs = jedi.Script(src, path=root / "report.py", project=jedi.Project(root)).get_references(1, 4, scope="project")
uses = [(r.module_path.name, r.line, r.column, r.name) for r in refs if not r.is_definition()]
print("jedi save_record via renamed import:", uses)
