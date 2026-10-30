"""Parsing iperf3 and ping output."""
import json

from emulation.traffic import (
    PAYLOAD_FRACTION,
    FlowResult,
    FlowSpec,
    parse_iperf3_udp,
    parse_ping,
)

# Shape of `iperf3 -u --json` client output (iperf3 3.16), trimmed to the fields used
# Shape of `iperf3 -u --json --get-server-output` client output (iperf3 3.16, server run with -J)
IPERF = {
    "start": {},
    "end": {
        "sum_sent": {"seconds": 3.0, "bytes": 5624400, "packets": 4687, "lost_packets": 0},
        "sum_received": {"seconds": 3.03, "bytes": 3654000, "packets": 4686, "lost_packets": 1641},
    },
    "server_output_json": {
        "intervals": [
            {"sum": {"start": 0, "end": 1.0001, "bytes": 1000000, "packets": 1000, "lost_packets": 0}},
            {"sum": {"start": 1.0001, "end": 2.0002, "bytes": 1300000, "packets": 1900, "lost_packets": 600}},
            {"sum": {"start": 2.0002, "end": 3.0003, "bytes": 1354000, "packets": 1786, "lost_packets": 432}},
        ]
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
    parse_iperf3_udp(json.dumps(IPERF), r, window=(1.0, 3.0))
    assert (r.sent_bytes, r.received_bytes, r.lost_packets, r.packets) == (5624400, 3654000, 1641, 4686)
    # demanded rates are wire rates; the payload share is 1000 / 1042 bytes
    assert r.demanded_bytes == 15e6 / 8 * 3.0 * PAYLOAD_FRACTION and round(PAYLOAD_FRACTION, 4) == 0.9597
    # only the server intervals inside the window count
    assert (r.window_received_bytes, r.window_packets, r.window_lost_packets) == (2654000, 3686, 1032)
    assert abs(r.window_seconds - 2.0002) < 1e-9
    assert round(r.loss_pct, 1) == 28.0 and r.error is None


def test_window_without_server_intervals_is_an_error():
    data = {k: v for k, v in IPERF.items() if k != "server_output_json"}
    r = FlowResult(0, 1e6)
    parse_iperf3_udp(json.dumps(data), r, window=(1.0, 3.0))
    assert r.window_seconds == 0 and r.error


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
