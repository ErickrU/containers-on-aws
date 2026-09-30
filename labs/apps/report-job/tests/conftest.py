"""Make ``report.py`` importable whether pytest is started as ``pytest`` or ``python -m pytest``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
