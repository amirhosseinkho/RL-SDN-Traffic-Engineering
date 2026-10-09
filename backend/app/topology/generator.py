"""Topology generator supporting multiple SDN topology types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from app.database.models import TopologyType
from app.database.schemas import TopologyConfig


@dataclass
class HostNode:
    name: str
    ip: str
    mac: str
    connected_switch: str
    port: int


@dataclass
class SwitchNode:
    name: str
    dpid: int


@dataclass
class LinkDef:
    src: str
    dst: str
    bandwidth: float  # Mbps
    latency: float  # ms
    loss: float  # %
    src_port: int = 0
    dst_port: int = 0


@dataclass
class TopologyDefinition:
    topology_type: TopologyType
    switches: list[SwitchNode] = field(default_factory=list)
    hosts: list[HostNode] = field(default_factory=list)
    links: list[LinkDef] = field(default_factory=list)
    graph: nx.Graph = field(default_factory=nx.Graph)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology_type": self.topology_type.value,
            "switches": [{"name": s.name, "dpid": s.dpid} for s in self.switches],
            "hosts": [
                {"name": h.name, "ip": h.ip, "mac": h.mac, "connected_switch": h.connected_switch}
                for h in self.hosts
            ],
            "links": [
                {
                    "src": lk.src,
                    "dst": lk.dst,
                    "bandwidth": lk.bandwidth,
                    "latency": lk.latency,
                    "loss": lk.loss,
                }
                for lk in self.links
            ],
        }

    def to_graph_data(self) -> dict[str, Any]:
        """Serialize for frontend visualization."""
        nodes = []
        for sw in self.switches:
            nodes.append(
                {"id": sw.name, "label": sw.name, "node_type": "switch", "dpid": sw.dpid}
            )
        for h in self.hosts:
            nodes.append(
                {
                    "id": h.name,
                    "label": h.name,
                    "node_type": "host",
                    "ip": h.ip,
                    "mac": h.mac,
                    "connected_switch": h.connected_switch,
                }
            )
        edges = []
        for i, lk in enumerate(self.links):
            edges.append(
                {
                    "id": f"e{i}",
                    "source": lk.src,
                    "target": lk.dst,
                    "bandwidth": lk.bandwidth,
                    "latency": lk.latency,
                    "loss": lk.loss,
                }
            )
        return {"nodes": nodes, "edges": edges}


class TopologyGenerator:
    """Generates various SDN topology configurations."""

    def generate(self, config: TopologyConfig) -> TopologyDefinition:
        generators = {
            TopologyType.LINEAR: self._linear,
            TopologyType.TREE: self._tree,
            TopologyType.FAT_TREE: self._fat_tree,
            TopologyType.SPINE_LEAF: self._spine_leaf,
            TopologyType.CUSTOM: self._custom,
        }
        fn = generators.get(config.topology_type)
        if fn is None:
            raise ValueError(f"Unsupported topology type: {config.topology_type}")
        return fn(config)

    # ─── Linear ──────────────────────────────────────────────────────────

    def _linear(self, cfg: TopologyConfig) -> TopologyDefinition:
        n = cfg.num_switches
        topo = TopologyDefinition(topology_type=TopologyType.LINEAR, config=cfg.model_dump())

        for i in range(n):
            sw = SwitchNode(name=f"s{i+1}", dpid=i + 1)
            topo.switches.append(sw)
            topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid)

        # Inter-switch links
        port_counter: dict[str, int] = {sw.name: 1 for sw in topo.switches}
        for i in range(n - 1):
            src, dst = f"s{i+1}", f"s{i+2}"
            sp, dp = port_counter[src], port_counter[dst]
            topo.links.append(
                LinkDef(src, dst, cfg.bandwidth, cfg.latency, cfg.loss, sp, dp)
            )
            port_counter[src] += 1
            port_counter[dst] += 1
            topo.graph.add_edge(src, dst, bandwidth=cfg.bandwidth, latency=cfg.latency)

        # Attach hosts evenly across switches
        hosts_per_switch = max(1, cfg.num_hosts // n)
        host_idx = 1
        for i, sw in enumerate(topo.switches):
            count = hosts_per_switch if i < n - 1 else cfg.num_hosts - host_idx + 1
            for _ in range(count):
                h = HostNode(
                    name=f"h{host_idx}",
                    ip=f"10.0.0.{host_idx}",
                    mac=f"00:00:00:00:00:{host_idx:02x}",
                    connected_switch=sw.name,
                    port=port_counter[sw.name],
                )
                topo.hosts.append(h)
                topo.links.append(
                    LinkDef(sw.name, h.name, cfg.bandwidth, cfg.latency, cfg.loss,
                            port_counter[sw.name], 0)
                )
                topo.graph.add_node(h.name, node_type="host", ip=h.ip)
                topo.graph.add_edge(sw.name, h.name, bandwidth=cfg.bandwidth, latency=cfg.latency)
                port_counter[sw.name] += 1
                host_idx += 1
                if host_idx > cfg.num_hosts:
                    break

        return topo

    # ─── Tree ────────────────────────────────────────────────────────────

    def _tree(self, cfg: TopologyConfig) -> TopologyDefinition:
        depth = cfg.depth or 2
        fanout = cfg.fanout or 2
        topo = TopologyDefinition(topology_type=TopologyType.TREE, config=cfg.model_dump())
        port_counter: dict[str, int] = {}

        sw_idx = [1]

        def add_switch() -> SwitchNode:
            sw = SwitchNode(name=f"s{sw_idx[0]}", dpid=sw_idx[0])
            sw_idx[0] += 1
            topo.switches.append(sw)
            port_counter[sw.name] = 1
            topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid)
            return sw

        def build(parent: SwitchNode | None, current_depth: int) -> SwitchNode:
            sw = add_switch()
            if parent:
                sp, dp = port_counter[parent.name], port_counter[sw.name]
                topo.links.append(LinkDef(parent.name, sw.name, cfg.bandwidth, cfg.latency, cfg.loss, sp, dp))
                topo.graph.add_edge(parent.name, sw.name, bandwidth=cfg.bandwidth, latency=cfg.latency)
                port_counter[parent.name] += 1
                port_counter[sw.name] += 1
            if current_depth < depth:
                for _ in range(fanout):
                    build(sw, current_depth + 1)
            return sw

        root = build(None, 1)

        # Attach hosts to leaf switches
        leaf_switches = [sw for sw in topo.switches if topo.graph.degree(sw.name) == 1 and sw != root]
        if not leaf_switches:
            leaf_switches = topo.switches[-fanout:]

        host_idx = 1
        hosts_per_leaf = max(1, cfg.num_hosts // len(leaf_switches))
        for i, sw in enumerate(leaf_switches):
            count = hosts_per_leaf if i < len(leaf_switches) - 1 else cfg.num_hosts - host_idx + 1
            for _ in range(count):
                h = HostNode(
                    name=f"h{host_idx}",
                    ip=f"10.0.0.{host_idx}",
                    mac=f"00:00:00:00:00:{host_idx:02x}",
                    connected_switch=sw.name,
                    port=port_counter[sw.name],
                )
                topo.hosts.append(h)
                topo.links.append(
                    LinkDef(sw.name, h.name, cfg.bandwidth, cfg.latency, cfg.loss,
                            port_counter[sw.name], 0)
                )
                topo.graph.add_node(h.name, node_type="host", ip=h.ip)
                topo.graph.add_edge(sw.name, h.name, bandwidth=cfg.bandwidth, latency=cfg.latency)
                port_counter[sw.name] += 1
                host_idx += 1
                if host_idx > cfg.num_hosts:
                    break

        topo.config["actual_switches"] = len(topo.switches)
        return topo

    # ─── Fat-Tree ────────────────────────────────────────────────────────

    def _fat_tree(self, cfg: TopologyConfig) -> TopologyDefinition:
        """Standard k-port fat-tree with k^3/4 hosts."""
        k = cfg.k or 4
        if k % 2 != 0:
            raise ValueError("k must be even for fat-tree topology")

        topo = TopologyDefinition(topology_type=TopologyType.FAT_TREE, config=cfg.model_dump())
        port_counter: dict[str, int] = {}

        num_core = (k // 2) ** 2
        num_pods = k
        num_agg_per_pod = k // 2
        num_edge_per_pod = k // 2
        num_hosts_per_edge = k // 2

        # Core switches
        core_switches: list[SwitchNode] = []
        for i in range(num_core):
            sw = SwitchNode(name=f"core{i+1}", dpid=1000 + i + 1)
            core_switches.append(sw)
            topo.switches.append(sw)
            port_counter[sw.name] = 1
            topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid, layer="core")

        # Pods
        host_idx = 1
        for pod in range(num_pods):
            agg_switches: list[SwitchNode] = []
            edge_switches: list[SwitchNode] = []

            for a in range(num_agg_per_pod):
                sw = SwitchNode(name=f"agg_p{pod}_a{a}", dpid=2000 + pod * 100 + a + 1)
                agg_switches.append(sw)
                topo.switches.append(sw)
                port_counter[sw.name] = 1
                topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid, layer="aggregation")

            for e in range(num_edge_per_pod):
                sw = SwitchNode(name=f"edge_p{pod}_e{e}", dpid=3000 + pod * 100 + e + 1)
                edge_switches.append(sw)
                topo.switches.append(sw)
                port_counter[sw.name] = 1
                topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid, layer="edge")

            # Agg ↔ Edge links
            for agg in agg_switches:
                for edge in edge_switches:
                    ap, ep = port_counter[agg.name], port_counter[edge.name]
                    topo.links.append(LinkDef(agg.name, edge.name, cfg.bandwidth, cfg.latency, cfg.loss, ap, ep))
                    topo.graph.add_edge(agg.name, edge.name, bandwidth=cfg.bandwidth, latency=cfg.latency)
                    port_counter[agg.name] += 1
                    port_counter[edge.name] += 1

            # Core ↔ Agg links
            for a, agg in enumerate(agg_switches):
                for stride in range(k // 2):
                    core_idx = a * (k // 2) + stride
                    core = core_switches[core_idx]
                    cp, ap = port_counter[core.name], port_counter[agg.name]
                    topo.links.append(LinkDef(core.name, agg.name, cfg.bandwidth * 2, cfg.latency, cfg.loss, cp, ap))
                    topo.graph.add_edge(core.name, agg.name, bandwidth=cfg.bandwidth * 2, latency=cfg.latency)
                    port_counter[core.name] += 1
                    port_counter[agg.name] += 1

            # Hosts on edge switches
            for edge in edge_switches:
                for _ in range(num_hosts_per_edge):
                    h = HostNode(
                        name=f"h{host_idx}",
                        ip=f"10.{pod}.{edge_switches.index(edge)}.{host_idx % 254 + 1}",
                        mac=f"00:00:{pod:02x}:{edge_switches.index(edge):02x}:00:{host_idx:02x}",
                        connected_switch=edge.name,
                        port=port_counter[edge.name],
                    )
                    topo.hosts.append(h)
                    topo.links.append(
                        LinkDef(edge.name, h.name, cfg.bandwidth, cfg.latency, cfg.loss,
                                port_counter[edge.name], 0)
                    )
                    topo.graph.add_node(h.name, node_type="host", ip=h.ip)
                    topo.graph.add_edge(edge.name, h.name, bandwidth=cfg.bandwidth, latency=cfg.latency)
                    port_counter[edge.name] += 1
                    host_idx += 1

        topo.config["actual_hosts"] = len(topo.hosts)
        topo.config["k"] = k
        return topo

    # ─── Spine-Leaf ──────────────────────────────────────────────────────

    def _spine_leaf(self, cfg: TopologyConfig) -> TopologyDefinition:
        num_spine = cfg.num_spine or 2
        num_leaf = cfg.num_leaf or 4
        hosts_per_leaf = max(1, cfg.num_hosts // num_leaf)

        topo = TopologyDefinition(topology_type=TopologyType.SPINE_LEAF, config=cfg.model_dump())
        port_counter: dict[str, int] = {}

        spine_switches: list[SwitchNode] = []
        for i in range(num_spine):
            sw = SwitchNode(name=f"spine{i+1}", dpid=100 + i + 1)
            spine_switches.append(sw)
            topo.switches.append(sw)
            port_counter[sw.name] = 1
            topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid, layer="spine")

        leaf_switches: list[SwitchNode] = []
        for i in range(num_leaf):
            sw = SwitchNode(name=f"leaf{i+1}", dpid=200 + i + 1)
            leaf_switches.append(sw)
            topo.switches.append(sw)
            port_counter[sw.name] = 1
            topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid, layer="leaf")

        # Full mesh spine ↔ leaf
        for spine in spine_switches:
            for leaf in leaf_switches:
                sp, lp = port_counter[spine.name], port_counter[leaf.name]
                topo.links.append(
                    LinkDef(spine.name, leaf.name, cfg.bandwidth * 2, cfg.latency, cfg.loss, sp, lp)
                )
                topo.graph.add_edge(spine.name, leaf.name, bandwidth=cfg.bandwidth * 2, latency=cfg.latency)
                port_counter[spine.name] += 1
                port_counter[leaf.name] += 1

        # Hosts on leaves
        host_idx = 1
        for i, leaf in enumerate(leaf_switches):
            count = hosts_per_leaf if i < num_leaf - 1 else cfg.num_hosts - host_idx + 1
            for _ in range(count):
                h = HostNode(
                    name=f"h{host_idx}",
                    ip=f"192.168.{i+1}.{host_idx % 254 + 1}",
                    mac=f"00:00:00:{i:02x}:00:{host_idx:02x}",
                    connected_switch=leaf.name,
                    port=port_counter[leaf.name],
                )
                topo.hosts.append(h)
                topo.links.append(
                    LinkDef(leaf.name, h.name, cfg.bandwidth, cfg.latency, cfg.loss,
                            port_counter[leaf.name], 0)
                )
                topo.graph.add_node(h.name, node_type="host", ip=h.ip)
                topo.graph.add_edge(leaf.name, h.name, bandwidth=cfg.bandwidth, latency=cfg.latency)
                port_counter[leaf.name] += 1
                host_idx += 1
                if host_idx > cfg.num_hosts:
                    break

        return topo

    # ─── Custom ──────────────────────────────────────────────────────────

    def _custom(self, cfg: TopologyConfig) -> TopologyDefinition:
        if not cfg.custom_data:
            raise ValueError("custom_data is required for custom topology type")

        data = cfg.custom_data
        topo = TopologyDefinition(topology_type=TopologyType.CUSTOM, config=cfg.model_dump())
        port_counter: dict[str, int] = {}

        for sw_data in data.get("switches", []):
            sw = SwitchNode(name=sw_data["name"], dpid=sw_data["dpid"])
            topo.switches.append(sw)
            port_counter[sw.name] = 1
            topo.graph.add_node(sw.name, node_type="switch", dpid=sw.dpid)

        for h_data in data.get("hosts", []):
            h = HostNode(
                name=h_data["name"],
                ip=h_data["ip"],
                mac=h_data.get("mac", "00:00:00:00:00:00"),
                connected_switch=h_data["connected_switch"],
                port=h_data.get("port", 1),
            )
            topo.hosts.append(h)
            topo.graph.add_node(h.name, node_type="host", ip=h.ip)

        for lk_data in data.get("links", []):
            lk = LinkDef(
                src=lk_data["src"],
                dst=lk_data["dst"],
                bandwidth=lk_data.get("bandwidth", cfg.bandwidth),
                latency=lk_data.get("latency", cfg.latency),
                loss=lk_data.get("loss", cfg.loss),
            )
            topo.links.append(lk)
            topo.graph.add_edge(lk.src, lk.dst, bandwidth=lk.bandwidth, latency=lk.latency)

        return topo
