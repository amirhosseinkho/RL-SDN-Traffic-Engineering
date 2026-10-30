"""Run the routing policies on an emulated network (Mininet + an os-ken/Ryu OpenFlow controller).

Only `topology` and `session` (and the scripts using them: `runner`, `milestone`) import Mininet, and
`controller_app` (run under osken-manager or ryu-manager) imports os-ken or Ryu; the other modules
import without them, which the unit tests rely on. See docs/emulation.md.
"""
import sys
from pathlib import Path

# The emulation reuses the backend's simulator, agents and topology generator
_BACKEND = str(Path(__file__).resolve().parents[1] / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
