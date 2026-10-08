"""Put scripts/pr_map and tests/ on the import path; import this before anything from them."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "pr_map"))
sys.path.insert(0, str(ROOT / "tests"))
