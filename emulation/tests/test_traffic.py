"""Parsing iperf3 and ping output."""
import json

from emulation.traffic import FlowResult, FlowSpec, parse_iperf3_udp, parse_ping

# Shape of `iperf3 -u --json` client output (iperf3 3.16), trimmed to the fields used
IPERF = {
    "start": {},
    "end": {
        "sum_sent": {"seconds": 3.0, "bytes": 5624400, "packets": 4687, "lost_packets": 0},
        "sum_received": {"seconds": 3.03, "bytes": 3654000, "packets": 4686, "lost_packets": 1641},
    },
}

PING = """PING 192.168.3.6 (192.168.3.6) 56(84) bytes of data.
64 bytes from 192.168.3.6: icmp_seq=1 ttl=64 time=21.9 ms
64 bytes from 192.168.3.6: icmp_seq=3 ttl=64 time=20.5 ms

--- 192.168.3.6 ping statistics ---
3 packets transmitted, 2 received, 33.3333% packet loss, time 2003ms
"""


def test_parse_iperf3_udp():
    r = FlowResult(0, demanded_bps=15e6)
    parse_iperf3_udp(json.dumps(IPERF), r)
    assert (r.sent_bytes, r.received_bytes, r.lost_packets, r.packets) == (5624400, 3654000, 1641, 4686)
    assert r.demanded_bytes == 15e6 / 8 * 3.0
    assert round(r.loss_pct, 1) == 35.0 and r.error is None


def test_parse_iperf3_error():
    r = FlowResult(0, 1e6)
    parse_iperf3_udp(json.dumps({"start": {}, "end": {}, "error": "unable to connect"}), r)
    assert r.error == "unable to connect" and r.received_bytes == 0
    r = FlowResult(0, 1e6)
    parse_iperf3_udp("iperf3: error", r)
    assert r.error.startswith("iperf3 output is not JSON")


def test_parse_ping():
    r = FlowResult(0, 1e6)
    parse_ping(PING, r)
    assert r.rtts_ms == [21.9, 20.5] and (r.pings_sent, r.pings_received) == (3, 2)


def test_flow_ports_are_unique_per_flow():
    flows = [FlowSpec(i, "h1", "h5", "a", "b") for i in range(16)]
    assert len({f.server_port for f in flows}) == 16 and len({f.client_port for f in flows}) == 16
    assert flows[3].five_tuple == ("a", "b", 17, 40004, 5204)
