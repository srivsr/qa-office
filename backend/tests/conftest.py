"""Pytest configuration — adds qa-office root and backend root to sys.path."""

import sys
from pathlib import Path

# qa-office root (agents/, services/, schemas.py, config/)
QA_ROOT = Path(__file__).parents[3]
BACKEND_ROOT = Path(__file__).parents[2]

for p in (str(QA_ROOT), str(BACKEND_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
