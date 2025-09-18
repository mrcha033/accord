"""Test configuration helpers."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is importable when tests run via tools like pre-commit
# where the project may not be installed as a package yet.
ROOT = Path(__file__).resolve().parent.parent
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
