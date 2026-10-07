"""Spike: resolve references to Python functions with jedi; compare with bare-name matches."""

import pathlib
import re
import sys
import time

import jedi

root = pathlib.Path(sys.argv[1]).resolve()
project = jedi.Project(root)
for rel, name in [(a.split(":")[0], a.split(":")[1]) for a in sys.argv[2:]]:
    f = root / rel
    src = f.read_text()
    line_no = next(i for i, text in enumerate(src.splitlines(), 1) if re.match(rf"\s*def {name}\b", text))
    col = src.splitlines()[line_no - 1].index(name)
    t = time.perf_counter()
    refs = jedi.Script(src, path=f, project=project).get_references(line_no, col, scope="project")
    calls = [r for r in refs if not r.is_definition()]
    bare = sum(len(re.findall(rf"\b{name}\(", p.read_text())) for p in root.rglob("*.py") if ".venv" not in p.parts)
    print(
        f"{rel}:{name}: jedi references={len(calls)} bare-name calls in repo={bare - 1} "
        f"seconds={time.perf_counter() - t:.1f}"
    )
    for r in calls[:5]:
        print("   ", r.module_path.relative_to(root), r.line)
