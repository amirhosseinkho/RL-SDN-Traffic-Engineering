"""Import Mininet when it is installed only for the system Python (apt package `mininet`)."""
from __future__ import annotations

import os
import sys

_SYSTEM_DIST_PACKAGES = "/usr/lib/python3/dist-packages"


def mininet_available() -> bool:
    try:
        import_mininet()
    except ImportError:
        return False
    return True


def import_mininet() -> None:
    """Make `import mininet` work from a virtualenv.

    The apt package installs Mininet into the system site-packages. Appending that directory
    (not prepending) keeps the virtualenv's own packages (numpy, torch, ...) first.
    """
    try:
        import mininet  # noqa: F401
        return
    except ImportError:
        if not os.path.isdir(os.path.join(_SYSTEM_DIST_PACKAGES, "mininet")):
            raise
    sys.path.append(_SYSTEM_DIST_PACKAGES)
    import mininet  # noqa: F401
