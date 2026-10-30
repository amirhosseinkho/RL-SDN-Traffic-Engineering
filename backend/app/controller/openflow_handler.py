"""OpenFlow 1.3 controller application (L2 learning, topology discovery, path installation).

Runs under os-ken, the maintained Ryu fork, or under Ryu (from backend/, so that `app` imports):
    PYTHONPATH=. osken-manager app/controller/openflow_handler.py --observe-links
    PYTHONPATH=. ryu-manager app/controller/openflow_handler.py --observe-links

It is not imported by the backend. The emulation uses its own app (emulation/controller_app.py),
which installs paths the same way (app.controller.flow_rules) but does no L2 learning: flooding
would loop in a spine-leaf topology.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from app.controller import flow_rules

try:  # os-ken
    from os_ken.base import app_manager
    from os_ken.controller import ofp_event
    from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from os_ken.lib.packet import ether_types, ethernet, packet
    from os_ken.ofproto import ofproto_v1_3
    from os_ken.topology import event as topo_event
    from os_ken.topology.api import get_all_host, get_all_link, get_all_switch

    BaseApp = app_manager.OSKenApp
except ImportError:  # Ryu, same API
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.lib.packet import ether_types, ethernet, packet
    from ryu.ofproto import ofproto_v1_3
    from ryu.topology import event as topo_event
    from ryu.topology.api import get_all_host, get_all_link, get_all_switch

    BaseApp = app_manager.RyuApp

logger = logging.getLogger(__name__)


class SDNController(BaseApp):
    """
    OpenFlow 1.3 SDN controller with:
    - MAC learning and L2 forwarding
    - Topology discovery via LLDP
    - Port statistics collection
    - Path installation (install_path)
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.mac_to_port: dict[int, dict[str, int]] = defaultdict(dict)
        self.datapaths: dict[int, object] = {}
        self.topology_data: dict = {"switches": [], "links": [], "hosts": []}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev) -> None:
        """Install table-miss flow on switch connect."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath

        # Table-miss: send to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, 0, match, actions)
        logger.info("Switch connected: dpid=%016x", datapath.id)

    def _add_flow(
        self,
        datapath,
        priority: int,
        match,
        actions,
        buffer_id=None,
        idle_timeout: int = 0,
        hard_timeout: int = 0,
    ) -> None:
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        kwargs = dict(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        if buffer_id:
            kwargs["buffer_id"] = buffer_id

        mod = parser.OFPFlowMod(**kwargs)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev) -> None:
        """L2 learning switch packet handler."""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return  # handled by topology discovery

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self._add_flow(datapath, 1, match, actions, msg.buffer_id, idle_timeout=20)
                return
            else:
                self._add_flow(datapath, 1, match, actions, idle_timeout=20)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)

    @set_ev_cls(topo_event.EventSwitchEnter)
    def switch_enter_handler(self, ev) -> None:
        switches = get_all_switch(self)
        links = get_all_link(self)
        hosts = get_all_host(self)
        self.topology_data = {
            "switches": [{"dpid": sw.dp.id} for sw in switches],
            "links": [
                {
                    "src": {"dpid": lk.src.dpid, "port_no": lk.src.port_no},
                    "dst": {"dpid": lk.dst.dpid, "port_no": lk.dst.port_no},
                }
                for lk in links
            ],
            "hosts": [{"mac": h.mac, "ipv4": h.ipv4} for h in hosts],
        }
        logger.info(
            "Topology updated: %d switches, %d links",
            len(self.topology_data["switches"]),
            len(self.topology_data["links"]),
        )

    def install_path(
        self, hops: list[flow_rules.Hop], src_ip: str, dst_ip: str, flow_id: int = 0
    ) -> None:
        """Install a path for src_ip -> dst_ip: permanent IPv4 rules, egress switch first.

        hops: (dpid, out_port) per switch in path order (flow_rules.path_hops builds them).
        """
        rules = flow_rules.path_rules(
            hops, flow_rules.ipv4_match(src_ip, dst_ip), flow_rules.flow_cookie(flow_id)
        )
        missing = [r.dpid for r in rules if r.dpid not in self.datapaths]
        if missing:
            raise KeyError(f"switches not connected: {missing}")
        for rule in rules:
            self.datapaths[rule.dpid].send_msg(flow_rules.to_flowmod(self.datapaths[rule.dpid], rule))
