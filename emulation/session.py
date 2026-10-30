"""Start the controller and the Mininet network for a mapping, install paths, tear down. Needs root."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.controller.flow_rules import path_hops

from emulation.controller_client import ControllerClient, start_controller
from emulation.mapping import EmulationMapping
from emulation.topology import build_network, start_network
from emulation.traffic import FlowSpec


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


class EmulationSession:
    def __init__(self, mapping: EmulationMapping, out_dir: Path, rest_port: int = 8080, of_port: int = 6653) -> None:
        self.mapping = mapping
        self.out_dir = out_dir
        self.rest_port = rest_port
        self.of_port = of_port
        self.client = ControllerClient(f"http://127.0.0.1:{rest_port}")
        self.net: Any = None
        self.controller: subprocess.Popen | None = None

    def __enter__(self) -> EmulationSession:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mn", "-c"], capture_output=True)  # leftovers of an interrupted run
        self.mapping.write(self.out_dir / "mapping.json")
        self.controller = start_controller(self.out_dir / "controller.log", self.rest_port, self.of_port)
        try:
            self.net = build_network(self.mapping, self.of_port)
            start_network(self.net)
            topo = self.client.wait_for(len(self.mapping.switches), 2 * len(self.mapping.links))
            (self.out_dir / "controller_topology.json").write_text(json.dumps(topo, indent=2))
            self._check_discovered(topo)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.net is not None:
            # Processes started in the hosts (iperf3 servers and clients, ping) outlive net.stop()
            kill_processes(processes_in_namespaces(h.pid for h in self.net.hosts))
            self.net.stop()
            self.net = None
        if self.controller is not None:
            self.controller.terminate()
            try:
                self.controller.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.controller.kill()
            self.controller = None

    def _check_discovered(self, topo: dict[str, Any]) -> None:
        """LLDP discovery must find exactly the links (and ports) of the mapping."""
        expected = set()
        for lk in self.mapping.links:
            a, b = self.mapping.switches[lk.src].dpid, self.mapping.switches[lk.dst].dpid
            expected.add((a, lk.src_port, b, lk.dst_port))
            expected.add((b, lk.dst_port, a, lk.src_port))
        found = {(d["src_dpid"], d["src_port"], d["dst_dpid"], d["dst_port"]) for d in topo["links"]}
        if found != expected:
            raise RuntimeError(f"discovered links differ from the mapping: missing {expected - found}, extra {found - expected}")

    def install(self, flow: FlowSpec, path: Sequence[str]) -> int:
        """Install both directions of a flow's path; returns the number of FlowMods sent."""
        dpids, ports = self.mapping.dpids, self.mapping.ports
        fwd = self.client.install_path(flow.flow_id, flow.src_ip, flow.dst_ip, path_hops(path, dpids, ports))
        rev = self.client.install_path(
            flow.flow_id, flow.dst_ip, flow.src_ip, path_hops(list(reversed(path)), dpids, ports), reverse=True
        )
        return fwd["added"] + fwd["deleted"] + rev["added"] + rev["deleted"]

    def dump_flows(self) -> str:
        out = []
        for sw in self.mapping.switches.values():
            text = self.net[sw.mininet].cmd(f"ovs-ofctl -O OpenFlow13 dump-flows {sw.mininet}")
            out.append(f"--- {sw.mininet} (dpid {sw.dpid})\n{text.strip()}")
        return "\n".join(out) + "\n"

    def tc_show(self, intf: str) -> str:
        return subprocess.run(
            ["sh", "-c", f"tc -s qdisc show dev {intf}; tc -s class show dev {intf}"],
            capture_output=True, text=True,
        ).stdout
