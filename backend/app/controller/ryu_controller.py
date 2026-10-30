"""Ryu SDN Controller integration layer.

This module bridges the FastAPI backend with the Ryu controller's REST API,
providing topology discovery, flow management, and traffic monitoring.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import networkx as nx

from app.config import get_settings
from app.controller import flow_rules

logger = logging.getLogger(__name__)
settings = get_settings()

RYU_BASE = f"http://{settings.ryu_host}:{settings.ryu_port}"


class RyuControllerClient:
    """Async HTTP client for the Ryu REST API."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "RyuControllerClient":
        self._client = httpx.AsyncClient(base_url=RYU_BASE, timeout=10.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("RyuControllerClient not initialized. Use async context manager.")
        return self._client

    # ─── Topology ────────────────────────────────────────────────────────

    async def get_switches(self) -> list[dict[str, Any]]:
        try:
            resp = await self.client.get("/v1.0/topology/switches")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.warning("Could not reach Ryu controller: %s", e)
            return []

    async def get_links(self) -> list[dict[str, Any]]:
        try:
            resp = await self.client.get("/v1.0/topology/links")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.warning("Could not reach Ryu controller: %s", e)
            return []

    async def get_hosts(self) -> list[dict[str, Any]]:
        try:
            resp = await self.client.get("/v1.0/topology/hosts")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.warning("Could not reach Ryu controller: %s", e)
            return []

    # ─── Flows ───────────────────────────────────────────────────────────

    async def get_flows(self, dpid: int | None = None) -> dict[str, Any]:
        try:
            url = f"/stats/flow/{dpid}" if dpid else "/stats/flow"
            resp = await self.client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.warning("Could not get flow stats: %s", e)
            return {}

    async def add_flow(self, dpid: int, flow_entry: dict[str, Any]) -> bool:
        try:
            payload = {"dpid": dpid, **flow_entry}
            resp = await self.client.post("/stats/flowentry/add", json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error("Failed to add flow to dpid=%d: %s", dpid, e)
            return False

    async def delete_flow(self, dpid: int, match: dict[str, Any]) -> bool:
        try:
            payload = {"dpid": dpid, "match": match}
            resp = await self.client.post("/stats/flowentry/delete", json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error("Failed to delete flow from dpid=%d: %s", dpid, e)
            return False

    async def clear_flows(self, dpid: int) -> bool:
        try:
            resp = await self.client.delete(f"/stats/flowentry/clear/{dpid}")
            resp.raise_for_status()
            return True
        except httpx.RequestError as e:
            logger.error("Failed to clear flows on dpid=%d: %s", dpid, e)
            return False

    # ─── Port Stats ──────────────────────────────────────────────────────

    async def get_port_stats(self, dpid: int | None = None) -> dict[str, Any]:
        try:
            url = f"/stats/port/{dpid}" if dpid else "/stats/port"
            resp = await self.client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.warning("Could not get port stats: %s", e)
            return {}

    async def get_queue_stats(self, dpid: int, port: int) -> dict[str, Any]:
        try:
            resp = await self.client.get(f"/stats/queue/{dpid}/{port}")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.warning("Could not get queue stats dpid=%d port=%d: %s", dpid, port, e)
            return {}

    # ─── Health ──────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        try:
            resp = await self.client.get("/v1.0/topology/switches", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False


class TopologyManager:
    """Discovers and maintains network topology from Ryu."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self._switches: list[dict] = []
        self._links: list[dict] = []
        self._hosts: list[dict] = []

    async def discover(self) -> None:
        async with RyuControllerClient() as ryu:
            self._switches = await ryu.get_switches()
            self._links = await ryu.get_links()
            self._hosts = await ryu.get_hosts()
        self._build_graph()

    def _build_graph(self) -> None:
        self.graph.clear()
        for sw in self._switches:
            dpid = sw["dpid"]
            self.graph.add_node(f"s{dpid}", node_type="switch", dpid=dpid, data=sw)
        for link in self._links:
            src = f"s{link['src']['dpid']}"
            dst = f"s{link['dst']['dpid']}"
            self.graph.add_edge(
                src,
                dst,
                src_port=_parse_hex(link["src"]["port_no"]),
                dst_port=_parse_hex(link["dst"]["port_no"]),
            )
        for host in self._hosts:
            hname = f"h_{host['mac'].replace(':', '')}"
            self.graph.add_node(hname, node_type="host", mac=host["mac"], ipv4=host.get("ipv4", []))
            for port in host.get("port", []):
                sw_node = f"s{port['dpid']}"
                if sw_node in self.graph:
                    self.graph.add_edge(sw_node, hname, src_port=_parse_hex(port["port_no"]))

    def get_shortest_path(self, src: str, dst: str) -> list[str] | None:
        try:
            return nx.shortest_path(self.graph, src, dst)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_all_paths(self, src: str, dst: str, k: int = 4) -> list[list[str]]:
        try:
            return list(nx.shortest_simple_paths(self.graph, src, dst))[:k]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def to_dict(self) -> dict[str, Any]:
        nodes = [
            {"id": n, **d} for n, d in self.graph.nodes(data=True)
        ]
        edges = [
            {"source": u, "target": v, **d} for u, v, d in self.graph.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}


class FlowManager:
    """Manages OpenFlow rules through the Ryu controller's ofctl_rest API.

    Rules come from app.controller.flow_rules: they match the flow's IPv4 source and destination,
    are permanent, carry a per-flow cookie and are sent egress switch first. (ofctl_rest sends no
    barrier between them, so the order is best effort; emulation/controller_app.py adds barriers.)
    """

    def __init__(self, topology_mgr: TopologyManager) -> None:
        self.topo = topology_mgr

    def _hops(self, path: list[str], egress_port: int | None) -> list[flow_rules.Hop]:
        graph = self.topo.graph
        dpids = {
            n: _parse_hex(d["dpid"]) for n, d in graph.nodes(data=True) if d.get("node_type") == "switch"
        }
        ports = {(u, v): d["src_port"] for u, v, d in graph.edges(data=True) if "src_port" in d}
        # Ryu only discovers hosts that have sent traffic to the controller, so a path may end
        # at the egress switch; egress_port is then the port towards the destination host
        return flow_rules.path_hops(path, dpids, ports, egress_port)

    async def install_path(
        self,
        path: list[str],
        src_ip: str,
        dst_ip: str,
        flow_id: int = 0,
        egress_port: int | None = None,
        priority: int = flow_rules.PATH_PRIORITY,
    ) -> bool:
        """Install forwarding rules for src_ip -> dst_ip along a path of TopologyManager nodes."""
        rules = flow_rules.path_rules(
            self._hops(path, egress_port),
            flow_rules.ipv4_match(src_ip, dst_ip),
            flow_rules.flow_cookie(flow_id),
            priority,
        )
        async with RyuControllerClient() as ryu:
            for rule in rules:
                entry = rule.to_ofctl_rest()
                if not await ryu.add_flow(entry.pop("dpid"), entry):
                    logger.error("Failed to install flow on dpid=%d", rule.dpid)
                    return False
        return True

    async def remove_path(
        self, path: list[str], src_ip: str, dst_ip: str, egress_port: int | None = None
    ) -> bool:
        match = flow_rules.ipv4_match(src_ip, dst_ip)
        async with RyuControllerClient() as ryu:
            for hop in self._hops(path, egress_port):
                await ryu.delete_flow(hop.dpid, dict(match))
        return True


def _parse_hex(value: int | str) -> int:
    """Ryu's topology REST API reports dpids and port numbers as hex strings
    ("00000000000000c9" = dpid 201, "00000003" = port 3)."""
    return value if isinstance(value, int) else int(value, 16)
