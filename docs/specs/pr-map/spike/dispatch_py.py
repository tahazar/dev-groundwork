"""Spike: jedi's goto on a method call on an untyped parameter, with dynamic_params on and off."""

import pathlib
import sys

import jedi

root = pathlib.Path(sys.argv[1]).resolve()
src = (root / "lib.py").read_text()
line = next(i for i, text in enumerate(src.splitlines(), 1) if "obj.save()" in text)
column = src.splitlines()[line - 1].index("save")
for setting in (True, False):
    jedi.settings.dynamic_params = setting
    jedi.settings.dynamic_params_for_other_modules = setting
    found = jedi.Script(src, path=root / "lib.py", project=jedi.Project(root)).goto(line, column)
    print(f"jedi goto obj.save, dynamic_params={setting}:", [(d.module_path.name, d.line, d.type) for d in found])
