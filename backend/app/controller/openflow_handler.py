"""Ryu OpenFlow 1.3 controller application.

Run this with:
    ryu-manager openflow_handler.py --observe-links --wsapi-port 8081
"""
from __future__ import annotations

import logging
from collections import defaultdict

from ryu.app import simple_switch_13
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import ether_types, ethernet, packet
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event as topo_event
from ryu.topology.api import get_all_host, get_all_link, get_all_switch

logger = logging.getLogger(__name__)


class SDNController(app_manager.RyuApp):
    """
    OpenFlow 1.3 SDN controller with:
    - MAC learning and L2 forwarding
    - Topology discovery via LLDP
    - Port statistics collection
    - REST API integration via Ryu's built-in wsgi
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        "wsgi": simple_switch_13.SimpleSwitch13,
    }

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
        self, path: list[tuple[int, int]], src_mac: str, dst_mac: str, priority: int = 10
    ) -> None:
        """Install a forwarding path across multiple switches."""
        for dpid, out_port in path:
            if dpid not in self.datapaths:
                logger.error("Switch dpid=%d not connected", dpid)
                continue
            datapath = self.datapaths[dpid]
            parser = datapath.ofproto_parser

            match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
            actions = [parser.OFPActionOutput(out_port)]
            self._add_flow(datapath, priority, match, actions, idle_timeout=300)
