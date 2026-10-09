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
        except httpx.RequestError as e:
            logger.error("Failed to add flow to dpid=%d: %s", dpid, e)
            return False

    async def delete_flow(self, dpid: int, match: dict[str, Any]) -> bool:
        try:
            payload = {"dpid": dpid, "match": match}
            resp = await self.client.post("/stats/flowentry/delete", json=payload)
            resp.raise_for_status()
            return True
        except httpx.RequestError as e:
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
                src_port=link["src"]["port_no"],
                dst_port=link["dst"]["port_no"],
            )
        for host in self._hosts:
            hname = f"h_{host['mac'].replace(':', '')}"
            self.graph.add_node(hname, node_type="host", mac=host["mac"], ipv4=host.get("ipv4", []))
            for port in host.get("port", []):
                sw_node = f"s{port['dpid']}"
                if sw_node in self.graph:
                    self.graph.add_edge(sw_node, hname, src_port=port["port_no"])

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
    """Manages OpenFlow rules through the Ryu controller."""

    def __init__(self, topology_mgr: TopologyManager) -> None:
        self.topo = topology_mgr

    async def install_path(
        self,
        path: list[str],
        src_mac: str,
        dst_mac: str,
        priority: int = 10,
    ) -> bool:
        """Install forwarding rules along a path."""
        async with RyuControllerClient() as ryu:
            for i in range(len(path) - 1):
                node = path[i]
                next_node = path[i + 1]

                if not self.topo.graph.has_node(node):
                    continue
                if self.topo.graph.nodes[node].get("node_type") != "switch":
                    continue

                dpid_str = node.lstrip("s")
                if not dpid_str.isdigit():
                    continue
                dpid = int(dpid_str)

                edge_data = self.topo.graph.get_edge_data(node, next_node)
                if not edge_data:
                    continue
                out_port = edge_data.get("src_port", 1)

                flow_entry = {
                    "priority": priority,
                    "match": {
                        "dl_src": src_mac,
                        "dl_dst": dst_mac,
                    },
                    "actions": [{"type": "OUTPUT", "port": out_port}],
                    "idle_timeout": 300,
                    "hard_timeout": 0,
                }
                success = await ryu.add_flow(dpid, flow_entry)
                if not success:
                    logger.error("Failed to install flow on dpid=%d", dpid)
                    return False
        return True

    async def remove_path(self, src_mac: str, dst_mac: str, path: list[str]) -> bool:
        async with RyuControllerClient() as ryu:
            for node in path:
                if not self.topo.graph.has_node(node):
                    continue
                if self.topo.graph.nodes[node].get("node_type") != "switch":
                    continue
                dpid_str = node.lstrip("s")
                if not dpid_str.isdigit():
                    continue
                dpid = int(dpid_str)
                match = {"dl_src": src_mac, "dl_dst": dst_mac}
                await ryu.delete_flow(dpid, match)
        return True
