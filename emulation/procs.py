"""Find and stop the processes running in Mininet hosts. No Mininet import, so it is unit-testable anywhere."""
from __future__ import annotations

import os
import signal
import time
from collections.abc import Iterable, Sequence
from pathlib import Path


def _net_ns(pid: int | str, proc: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(proc / str(pid) / "ns" / "net")
    except OSError:  # process gone, or not ours to inspect
        return None
    return st.st_dev, st.st_ino


def processes_in_namespaces(anchor_pids: Iterable[int], proc: Path = Path("/proc")) -> list[int]:
    """PIDs of all processes sharing a network namespace with one of anchor_pids (anchors excluded).

    Mininet hosts are network namespaces held open by a shell (`host.pid`); everything started in a
    host (iperf3 servers and clients, ping) runs in its namespace and is not stopped by `net.stop()`.
    """
    anchors = {int(p) for p in anchor_pids}
    namespaces = {ns for p in anchors if (ns := _net_ns(p, proc)) is not None}
    found = []
    for entry in proc.iterdir():
        if entry.name.isdigit() and int(entry.name) not in anchors and _net_ns(entry.name, proc) in namespaces:
            found.append(int(entry.name))
    return sorted(found)


def kill_processes(pids: Sequence[int], grace_s: float = 2.0) -> None:
    """SIGTERM, then SIGKILL whatever is still alive after grace_s."""
    def signal_all(sig: int) -> list[int]:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, sig)
                alive.append(pid)
            except ProcessLookupError:
                pass
        return alive
    if not signal_all(signal.SIGTERM):
        return
    deadline = time.time() + grace_s
    while time.time() < deadline and signal_all(0):
        time.sleep(0.1)
    signal_all(signal.SIGKILL)
