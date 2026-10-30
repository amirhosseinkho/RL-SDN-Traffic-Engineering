"""Run the routing policies on an emulated network (Mininet + an os-ken/Ryu OpenFlow controller).

Only `mapping`, `observation`, `policies` and `measure` are importable without Mininet; see
docs/emulation.md.
"""
import sys
from pathlib import Path

# The emulation reuses the backend's simulator, agents and topology generator
_BACKEND = str(Path(__file__).resolve().parents[1] / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
