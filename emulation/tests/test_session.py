import os
import signal
import subprocess
import sys
import time

import pytest

from emulation.session import kill_processes, processes_in_namespaces


def _fake_proc(tmp_path, namespaces):
    """A /proc with one ns/net file per pid; pids in the same namespace share the inode (hard links)."""
    first = {}
    for pid, ns in namespaces.items():
        d = tmp_path / str(pid) / "ns"
        d.mkdir(parents=True)
        if ns in first:
            os.link(first[ns], d / "net")
        else:
            (d / "net").write_text(ns)
            first[ns] = d / "net"
    (tmp_path / "self").mkdir()  # non-numeric entries are ignored
    return tmp_path


def test_finds_processes_in_the_hosts_namespaces_only(tmp_path):
    # 10 and 20 are host shells; 11, 12 run in host 10, 21 in host 20; 1 and 30 are elsewhere
    proc = _fake_proc(tmp_path, {1: "root", 10: "h1", 11: "h1", 12: "h1", 20: "h2", 21: "h2", 30: "other"})
    assert processes_in_namespaces([10, 20], proc) == [11, 12, 21]


def test_missing_anchor_and_vanished_processes_are_skipped(tmp_path):
    proc = _fake_proc(tmp_path, {10: "h1", 11: "h1"})
    (tmp_path / "99").mkdir()  # a pid without ns/net, e.g. exited meanwhile
    assert processes_in_namespaces([10, 404], proc) == [11]
    assert processes_in_namespaces([404], proc) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="POSIX signals")
def test_kill_processes_terminates_and_kills():
    polite = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    stubborn = subprocess.Popen([sys.executable, "-c",
                                 "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(1, flush=True); time.sleep(60)"],
                                stdout=subprocess.PIPE)
    stubborn.stdout.readline()  # SIGTERM handler installed
    start = time.time()
    kill_processes([polite.pid, stubborn.pid], grace_s=0.5)
    assert polite.wait(timeout=5) == -signal.SIGTERM
    assert stubborn.wait(timeout=5) == -signal.SIGKILL
    assert time.time() - start < 5
