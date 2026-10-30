"""Mapping from the simulator's TopologyDefinition to the emulated network.

Names: Mininet nodes keep the simulator's names (spine1, leaf3, h5). Datapath ids are the
generator's (spine1 = 101, leaf1 = 201, ...) and are set explicitly, because Mininet would
otherwise derive them from the digits in the name, and spine1 and leaf1 would both get dpid 1.

Ports: every link uses the generator's port numbers (LinkDef.src_port/dst_port, HostNode.port),
passed to Mininet explicitly, so interface spine1-eth3 is OpenFlow port 3 of spine1. Host
interfaces are <host>-eth0.

Capacity: switch-to-switch links get the simulator's bandwidth times capacity_scale and the
simulator's latency as netem delay. Host access links are not modelled in the simulator, so they
are left unshaped. Pure Python; no Mininet import.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.topology.generator import TopologyDefinition

IP_PREFIX_LEN = 16  # the generator's host IPs are 192.168.<leaf>.<n>; one /16 puts them on one subnet


@dataclass
class SwitchMap:
    name: str
    mininet: str
    dpid: int

    @property
    def dpid_hex(self) -> str:
        return f"{self.dpid:016x}"


@dataclass
class HostMap:
    name: str
    mininet: str
    ip: str
    mac: str
    switch: str
    switch_port: int
    intf: str


@dataclass
class LinkMap:
    src: str
    dst: str
    src_port: int
    dst_port: int
    src_intf: str
    dst_intf: str
    sim_bandwidth_mbps: float
    bandwidth_mbps: float  # emulated, per direction
    delay_ms: float
    max_queue_pkts: int


@dataclass
class EmulationMapping:
    capacity_scale: float
    max_queue_pkts: int
    switches: dict[str, SwitchMap] = field(default_factory=dict)
    hosts: dict[str, HostMap] = field(default_factory=dict)
    links: list[LinkMap] = field(default_factory=list)

    @property
    def dpids(self) -> dict[str, int]:
        return {name: sw.dpid for name, sw in self.switches.items()}

    @property
    def ports(self) -> dict[tuple[str, str], int]:
        """(node, neighbour) -> port number on node towards neighbour, for every link."""
        ports: dict[tuple[str, str], int] = {}
        for lk in self.links:
            ports[(lk.src, lk.dst)] = lk.src_port
            ports[(lk.dst, lk.src)] = lk.dst_port
        for h in self.hosts.values():
            ports[(h.switch, h.name)] = h.switch_port
            ports[(h.name, h.switch)] = 0
        return ports

    def link(self, u: str, v: str) -> LinkMap:
        for lk in self.links:
            if (lk.src, lk.dst) in ((u, v), (v, u)):
                return lk
        raise KeyError(f"no switch link {u}-{v}")

    def intf(self, u: str, v: str) -> str:
        """Interface on u that sends towards v (where u's egress qdisc for u->v lives)."""
        return f"{self.switches[u].mininet}-eth{self.ports[(u, v)]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity_scale": self.capacity_scale,
            "max_queue_pkts": self.max_queue_pkts,
            "ip_prefix_len": IP_PREFIX_LEN,
            "switches": {k: {**asdict(v), "dpid_hex": v.dpid_hex} for k, v in self.switches.items()},
            "hosts": {k: asdict(v) for k, v in self.hosts.items()},
            "links": [asdict(lk) for lk in self.links],
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))


def build_mapping(
    topo: TopologyDefinition, capacity_scale: float, max_queue_pkts: int = 25
) -> EmulationMapping:
    if not 0 < capacity_scale <= 1:
        raise ValueError("capacity_scale must be in (0, 1]")
    m = EmulationMapping(capacity_scale=capacity_scale, max_queue_pkts=max_queue_pkts)
    for sw in topo.switches:
        m.switches[sw.name] = SwitchMap(sw.name, sw.name, sw.dpid)
    if len({sw.dpid for sw in topo.switches}) != len(topo.switches):
        raise ValueError("duplicate dpids in topology")

    host_names = {h.name for h in topo.hosts}
    for h in topo.hosts:
        m.hosts[h.name] = HostMap(
            h.name, h.name, h.ip, h.mac, h.connected_switch, h.port, f"{h.name}-eth0"
        )
    for lk in topo.links:
        if lk.src in host_names or lk.dst in host_names:
            continue  # host links come from HostNode above
        if lk.src_port <= 0 or lk.dst_port <= 0:
            raise ValueError(f"link {lk.src}-{lk.dst} has no port numbers")
        m.links.append(
            LinkMap(
                src=lk.src,
                dst=lk.dst,
                src_port=lk.src_port,
                dst_port=lk.dst_port,
                src_intf=f"{lk.src}-eth{lk.src_port}",
                dst_intf=f"{lk.dst}-eth{lk.dst_port}",
                sim_bandwidth_mbps=lk.bandwidth,
                bandwidth_mbps=lk.bandwidth * capacity_scale,
                delay_ms=lk.latency,
                max_queue_pkts=max_queue_pkts,
            )
        )

    # Every port number must be unique per switch, or Mininet would silently renumber
    used: dict[str, set[int]] = {}
    for (node, _), port in m.ports.items():
        if node in m.switches:
            if port in used.setdefault(node, set()):
                raise ValueError(f"port {port} used twice on {node}")
            used[node].add(port)
    return m


def experiment_topology() -> TopologyDefinition:
    """The topology of the second experiment (experiments/second_experiment/run.sh)."""
    from app.database.models import TopologyType
    from app.database.schemas import TopologyConfig
    from app.topology.generator import TopologyGenerator

    cfg = TopologyConfig(
        topology_type=TopologyType.SPINE_LEAF, num_switches=6, num_hosts=8,
        bandwidth=100.0, latency=5.0, loss=0.0, name="eval-topology",
    )
    return TopologyGenerator().generate(cfg)
