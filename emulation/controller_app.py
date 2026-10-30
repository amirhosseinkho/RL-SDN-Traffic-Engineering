"""OpenFlow 1.3 controller app for the emulation: proactive path rules, port statistics, REST API.

Runs under os-ken (the maintained Ryu fork, `osken-manager`) or Ryu (`ryu-manager`):

    osken-manager --observe-links emulation/controller_app.py

Behaviour:
- On connect, a switch gets a priority-0 table-miss rule that drops. Nothing is flooded or learned:
  packets are forwarded only by path rules installed through the REST API (and LLDP, which the
  topology discovery app sends to the controller).
- Port statistics of every switch are requested every second.
- REST API (JSON, port EMU_REST_PORT, default 8080):
    GET    /health
    GET    /topology        switches and links found by LLDP discovery
    GET    /stats/ports     latest counters per (dpid, port), with the switch's own duration
    POST   /paths           install one direction of one flow's path, replacing its previous path
                            {"flow_id": 3, "reverse": false, "src_ip": ..., "dst_ip": ...,
                             "hops": [[dpid, out_port], ...]}   (hops in path order)
    DELETE /paths           remove every path rule
    GET    /paths           installed paths and the number of FlowMods sent so far

Path rules are built by app.controller.flow_rules (shared with the backend): match on
eth_type/ipv4_src/ipv4_dst, permanent, one cookie per flow and direction. They are sent egress
switch first, each followed by a barrier, so a switch has its rule before traffic can reach it;
stale rules on switches the flow no longer crosses are deleted last.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.controller import flow_rules  # noqa: E402

try:  # os-ken
    from os_ken.app.ofctl import api as ofctl_api
    from os_ken.base import app_manager
    from os_ken.controller import ofp_event
    from os_ken.controller.handler import (
        CONFIG_DISPATCHER,
        DEAD_DISPATCHER,
        MAIN_DISPATCHER,
        set_ev_cls,
    )
    from os_ken.lib import hub
    from os_ken.ofproto import ofproto_v1_3
    from os_ken.topology.api import get_all_link, get_all_switch

    BaseApp = app_manager.OSKenApp
except ImportError:  # Ryu, same API
    from ryu.app.ofctl import api as ofctl_api
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import (
        CONFIG_DISPATCHER,
        DEAD_DISPATCHER,
        MAIN_DISPATCHER,
        set_ev_cls,
    )
    from ryu.lib import hub
    from ryu.ofproto import ofproto_v1_3
    from ryu.topology.api import get_all_link, get_all_switch

    BaseApp = app_manager.RyuApp

logger = logging.getLogger(__name__)

REST_PORT = int(os.environ.get("EMU_REST_PORT", "8080"))
STATS_INTERVAL_S = 1.0


class EmulationController(BaseApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.datapaths: dict[int, object] = {}
        self.port_stats: dict[tuple[int, int], dict] = {}
        self.installed: dict[int, list[flow_rules.FlowRule]] = {}  # cookie -> rules
        self.flowmods_sent = 0
        self._lock = hub.Semaphore()
        hub.spawn(self._poll_stats)
        server = hub.WSGIServer(("0.0.0.0", REST_PORT), self._wsgi)
        hub.spawn(server.serve_forever)
        logger.info("REST API on port %d", REST_PORT)

    # ─── Switches ────────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev) -> None:
        dp = ev.msg.datapath
        parser = dp.ofproto_parser
        # Table-miss: drop (no actions)
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0, match=parser.OFPMatch(), instructions=[]))
        logger.info("switch connected: dpid=%d", dp.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev) -> None:
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER and dp.id is not None:
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER and dp.id in self.datapaths:
            del self.datapaths[dp.id]
            logger.warning("switch disconnected: dpid=%d", dp.id)

    # ─── Port statistics ─────────────────────────────────────────────────

    def _poll_stats(self) -> None:
        while True:
            for dp in list(self.datapaths.values()):
                parser, ofp = dp.ofproto_parser, dp.ofproto
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
            hub.sleep(STATS_INTERVAL_S)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev) -> None:
        now = time.time()
        dpid = ev.msg.datapath.id
        for s in ev.msg.body:
            if s.port_no > 0xFFFFFF00:  # OFPP_LOCAL and other reserved ports
                continue
            self.port_stats[(dpid, s.port_no)] = {
                "dpid": dpid,
                "port_no": s.port_no,
                "rx_packets": s.rx_packets,
                "tx_packets": s.tx_packets,
                "rx_bytes": s.rx_bytes,
                "tx_bytes": s.tx_bytes,
                "rx_dropped": s.rx_dropped,
                "tx_dropped": s.tx_dropped,
                "rx_errors": s.rx_errors,
                "tx_errors": s.tx_errors,
                # Time since the port was added, measured by the switch: rates use this, not the
                # arrival time of the reply
                "duration_s": s.duration_sec + s.duration_nsec / 1e9,
                "received_at": now,
            }

    # ─── Path rules ──────────────────────────────────────────────────────

    def _send_and_barrier(self, dp, msg) -> None:
        dp.send_msg(msg)
        ofctl_api.send_msg(self, dp.ofproto_parser.OFPBarrierRequest(dp), reply_cls=dp.ofproto_parser.OFPBarrierReply)
        self.flowmods_sent += 1

    def install_path(self, flow_id: int, reverse: bool, src_ip: str, dst_ip: str, hops: list[flow_rules.Hop]) -> dict:
        """Install one direction of a flow, replacing that direction's previous path."""
        missing = [h.dpid for h in hops if h.dpid not in self.datapaths]
        if missing:
            raise KeyError(f"switches not connected: {missing}")
        cookie = flow_rules.flow_cookie(flow_id, reverse)
        new = flow_rules.path_rules(hops, flow_rules.ipv4_match(src_ip, dst_ip), cookie)
        with self._lock:
            adds, deletes = flow_rules.plan_update(self.installed.get(cookie, []), new)
            for rule in adds:  # egress first
                dp = self.datapaths[rule.dpid]
                self._send_and_barrier(dp, flow_rules.to_flowmod(dp, rule))
            for rule in deletes:
                dp = self.datapaths.get(rule.dpid)
                if dp is not None:
                    self._send_and_barrier(dp, flow_rules.to_flowmod(dp, rule, delete=True))
            self.installed[cookie] = new
        return {"cookie": cookie, "added": len(adds), "deleted": len(deletes)}

    def clear_paths(self) -> int:
        with self._lock:
            for dp in self.datapaths.values():
                self._send_and_barrier(dp, flow_rules.delete_all_flowmod(dp))
            self.installed.clear()
        return len(self.datapaths)

    # ─── REST API ────────────────────────────────────────────────────────

    def _topology(self) -> dict:
        return {
            "switches": sorted(sw.dp.id for sw in get_all_switch(self)),
            "links": sorted(
                (
                    {"src_dpid": lk.src.dpid, "src_port": lk.src.port_no, "dst_dpid": lk.dst.dpid, "dst_port": lk.dst.port_no}
                    for lk in get_all_link(self)
                ),
                key=lambda d: (d["src_dpid"], d["src_port"]),
            ),
            "connected": sorted(self.datapaths),
        }

    def _wsgi(self, environ, start_response):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "")
        try:
            if method == "GET" and path == "/health":
                status, body = "200 OK", {"ok": True, "connected": len(self.datapaths)}
            elif method == "GET" and path == "/topology":
                status, body = "200 OK", self._topology()
            elif method == "GET" and path == "/stats/ports":
                status, body = "200 OK", {"ports": list(self.port_stats.values())}
            elif method == "GET" and path == "/paths":
                status, body = "200 OK", {
                    "flowmods_sent": self.flowmods_sent,
                    "paths": {str(c): [[r.dpid, r.out_port] for r in rules] for c, rules in self.installed.items()},
                }
            elif method == "POST" and path == "/paths":
                length = int(environ.get("CONTENT_LENGTH") or 0)
                req = json.loads(environ["wsgi.input"].read(length))
                hops = [flow_rules.Hop(int(d), int(p)) for d, p in req["hops"]]
                result = self.install_path(int(req["flow_id"]), bool(req.get("reverse", False)), req["src_ip"], req["dst_ip"], hops)
                status, body = "200 OK", {**result, "flowmods_sent": self.flowmods_sent}
            elif method == "DELETE" and path == "/paths":
                status, body = "200 OK", {"switches": self.clear_paths(), "flowmods_sent": self.flowmods_sent}
            else:
                status, body = "404 Not Found", {"error": f"{method} {path}"}
        except (KeyError, ValueError, TypeError) as e:
            status, body = "400 Bad Request", {"error": str(e)}
        data = json.dumps(body).encode()
        start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(data)))])
        return [data]
