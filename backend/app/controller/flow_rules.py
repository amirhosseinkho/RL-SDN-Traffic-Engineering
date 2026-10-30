"""OpenFlow 1.3 rules for installing a routing path, independent of the controller framework.

A path is a list of node names (host, switch, ..., switch, host). It becomes one rule per switch
that matches the flow's IPv4 source and destination and outputs on the port towards the next node.
Rules are returned egress switch first: installing them in that order means a packet never reaches
a switch before the switch has a rule for it.

Used by the os-ken/Ryu apps (openflow_handler.py, emulation/controller_app.py) and by
FlowManager in ryu_controller.py (through Ryu's ofctl_rest API). Pure Python, no controller import.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ETH_TYPE_IPV4 = 0x0800
PATH_PRIORITY = 100

# Every path rule carries a cookie in this namespace, so all of them can be removed at once
COOKIE_BASE = 0x5D0 << 48
COOKIE_NAMESPACE_MASK = 0xFFFF << 48
COOKIE_MASK_ALL = 0xFFFFFFFFFFFFFFFF


@dataclass(frozen=True)
class Hop:
    dpid: int
    out_port: int


@dataclass(frozen=True)
class FlowRule:
    dpid: int
    match: tuple[tuple[str, Any], ...]  # sorted (field, value) pairs, in os-ken/Ryu OXM field names
    out_port: int
    priority: int
    cookie: int

    @property
    def match_dict(self) -> dict[str, Any]:
        return dict(self.match)

    def to_ofctl_rest(self) -> dict[str, Any]:
        """Body for Ryu's ofctl_rest POST /stats/flowentry/add."""
        return {
            "dpid": self.dpid,
            "cookie": self.cookie,
            "priority": self.priority,
            "match": self.match_dict,
            "actions": [{"type": "OUTPUT", "port": self.out_port}],
            "idle_timeout": 0,
            "hard_timeout": 0,
        }


def flow_cookie(flow_id: int, reverse: bool = False) -> int:
    """Cookie of one direction of one flow: namespace | flow_id << 1 | direction."""
    if flow_id < 0 or flow_id >= 1 << 46:
        raise ValueError(f"flow_id out of range: {flow_id}")
    return COOKIE_BASE | (flow_id << 1) | int(reverse)


def ipv4_match(src_ip: str, dst_ip: str) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted({"eth_type": ETH_TYPE_IPV4, "ipv4_src": src_ip, "ipv4_dst": dst_ip}.items()))


def path_hops(
    path: Sequence[str],
    dpids: Mapping[str, int],
    ports: Mapping[tuple[str, str], int],
    egress_port: int | None = None,
) -> list[Hop]:
    """(dpid, out_port) for every switch on a path, in path order.

    dpids: switch name -> datapath id (hosts are absent). ports: (node, next node) -> port number
    on node towards next node. A missing link raises KeyError instead of silently skipping a hop.
    A path normally ends at the destination host; if it ends at a switch, egress_port is the
    port on that switch towards the destination.
    """
    hops = []
    for node, nxt in zip(path, path[1:]):
        if node not in dpids:
            continue
        if (node, nxt) not in ports:
            raise KeyError(f"no port on {node} towards {nxt}")
        hops.append(Hop(dpids[node], ports[(node, nxt)]))
    if path and path[-1] in dpids:
        if egress_port is None:
            raise ValueError(f"path ends at switch {path[-1]}: egress_port is required")
        hops.append(Hop(dpids[path[-1]], egress_port))
    return hops


def path_rules(
    hops: Sequence[Hop],
    match: tuple[tuple[str, Any], ...],
    cookie: int,
    priority: int = PATH_PRIORITY,
) -> list[FlowRule]:
    """One rule per hop, egress switch first."""
    return [FlowRule(h.dpid, match, h.out_port, priority, cookie) for h in reversed(hops)]


def plan_update(
    old: Sequence[FlowRule], new: Sequence[FlowRule]
) -> tuple[list[FlowRule], list[FlowRule]]:
    """Rules to add (egress first) and stale rules to delete when a flow moves from old to new.

    Rules already installed unchanged are skipped. A rule on a switch that stays on the path but
    changes its output port is overwritten by the add (same match and priority). Deletes come
    after all adds, once the ingress switch already sends the flow along the new path.
    """
    old_by_dpid = {r.dpid: r for r in old}
    new_dpids = {r.dpid for r in new}
    adds = [r for r in new if old_by_dpid.get(r.dpid) != r]
    deletes = [r for r in old if r.dpid not in new_dpids]
    return adds, deletes


def to_flowmod(datapath: Any, rule: FlowRule, delete: bool = False) -> Any:
    """OFPFlowMod for a rule, built with the datapath's own parser (os-ken or Ryu, OpenFlow 1.3).

    Adds are permanent (no idle or hard timeout). Deletes are strict (same match and priority)
    and also filter on the rule's cookie.
    """
    ofp = datapath.ofproto
    parser = datapath.ofproto_parser
    match = parser.OFPMatch(**rule.match_dict)
    if delete:
        return parser.OFPFlowMod(
            datapath=datapath,
            cookie=rule.cookie,
            cookie_mask=COOKIE_MASK_ALL,
            command=ofp.OFPFC_DELETE_STRICT,
            priority=rule.priority,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
            match=match,
        )
    actions = [parser.OFPActionOutput(rule.out_port)]
    return parser.OFPFlowMod(
        datapath=datapath,
        cookie=rule.cookie,
        command=ofp.OFPFC_ADD,
        priority=rule.priority,
        idle_timeout=0,
        hard_timeout=0,
        match=match,
        instructions=[parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)],
    )


def delete_all_flowmod(datapath: Any) -> Any:
    """OFPFlowMod that removes every path rule (any cookie in COOKIE_BASE's namespace)."""
    ofp = datapath.ofproto
    parser = datapath.ofproto_parser
    return parser.OFPFlowMod(
        datapath=datapath,
        cookie=COOKIE_BASE,
        cookie_mask=COOKIE_NAMESPACE_MASK,
        table_id=ofp.OFPTT_ALL,
        command=ofp.OFPFC_DELETE,
        out_port=ofp.OFPP_ANY,
        out_group=ofp.OFPG_ANY,
        match=parser.OFPMatch(),
    )
