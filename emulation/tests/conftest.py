"""Make `emulation` (and through it the backend's `app`) importable when pytest runs from anywhere."""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import emulation  # noqa: E402,F401  (adds backend/ to sys.path)
