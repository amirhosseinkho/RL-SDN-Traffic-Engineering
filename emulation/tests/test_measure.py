"""Turning port counters and tc samples into link features."""
import json

import pytest

from emulation.measure import (
    DirectionStats,
    direction_features,
    parse_tc_json,
    port_delta,
    qdisc_window,
)

# Shape of `tc -s -j qdisc show` (iproute2 6.1) for a Mininet TCLink interface, trimmed
TC = [
    {"kind": "htb", "handle": "5:", "dev": "spine1-eth1", "root": True, "bytes": 1808293, "packets": 1469,
     "drops": 782, "backlog": 36018, "qlen": 29},
    {"kind": "netem", "handle": "10:", "dev": "spine1-eth1", "parent": "5:1",
     "options": {"limit": 30, "delay": {"delay": 0.005, "jitter": 0, "correlation": 0}},
     "bytes": 1808293, "packets": 1469, "drops": 782, "backlog": 36018, "qlen": 29},
    {"kind": "fq_codel", "dev": "eth0", "bytes": 1, "packets": 1, "drops": 0, "backlog": 0, "qlen": 0},
]


def test_parse_tc_json_keeps_netem_only():
    q = parse_tc_json(json.dumps(TC))
    assert list(q) == ["spine1-eth1"]
    assert (q["spine1-eth1"]["qlen"], q["spine1-eth1"]["drops"], q["spine1-eth1"]["delay_s"]) == (29, 782, 0.005)


def test_port_delta_uses_switch_duration():
    a = {"tx_bytes": 1000, "tx_packets": 1, "duration_s": 10.0}
    b = {"tx_bytes": 1000 + 2_500_000, "tx_packets": 2401, "duration_s": 12.0}
    assert port_delta(a, b) == (1_250_000, 1200, 2.0)
    assert port_delta(b, a)[2] == 0.0


def test_qdisc_window_mean_and_deltas():
    samples = [(t, {"x": {"qlen": t, "backlog": 10 * t, "drops": 3 * t, "packets": 100 * t, "delay_s": 0.005}}) for t in range(10)]
    w = qdisc_window(samples, "x", 2, 5)
    assert w == {"qlen": 3.5, "backlog": 35.0, "drops": 9, "packets": 300, "delay_s": 0.005}
    assert qdisc_window(samples, "missing", 2, 5)["packets"] == 0


def test_direction_features():
    s = DirectionStats(rate_bps=8e6, rate_pps=1000, mean_qlen_pkts=15, mean_backlog_bytes=20000, drops=10, sent_pkts=990, delay_s=0.005)
    occ, qdelay_ms, loss = direction_features(s, 10e6, 25)
    assert occ == pytest.approx((15 - 5) / 25)  # 5 packets are in the delay line
    assert qdelay_ms == pytest.approx((20000 - 5000) * 8 / 10e6 * 1000)
    assert loss == pytest.approx(1.0)
