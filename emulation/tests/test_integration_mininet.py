"""End-to-end: topology + controller, install a path, 2 s of traffic, confirm the path with tshark.

Runs only as root on Linux with Mininet, Open vSwitch, iperf3, tshark and os-ken (or Ryu):
    sudo <venv>/bin/python -m pytest emulation/tests -m mininet
"""
import os
import shutil
import sys

import pytest

from emulation._compat import mininet_available

pytestmark = [
    pytest.mark.mininet,
    pytest.mark.skipif(
        not sys.platform.startswith("linux")
        or os.geteuid() != 0
        or not mininet_available()
        or not all(shutil.which(t) for t in ("ovs-vsctl", "iperf3", "tshark"))
        or not (shutil.which("osken-manager") or shutil.which("ryu-manager")),
        reason="needs root on Linux with Mininet, Open vSwitch, iperf3, tshark and os-ken/Ryu",
    ),
]


def test_installed_path_carries_the_traffic(tmp_path):
    from emulation.mapping import build_mapping, experiment_topology
    from emulation.session import EmulationSession
    from emulation.traffic import FlowSpec, run_traffic, start_servers
    from emulation.verify_paths import capture, check, read_counts, spine_interfaces

    mapping = build_mapping(experiment_topology(), capacity_scale=0.05)
    path = ["h1", "leaf1", "spine2", "leaf3", "h5"]
    flow = FlowSpec(0, "h1", "h5", mapping.hosts["h1"].ip, mapping.hosts["h5"].ip)

    with EmulationSession(mapping, tmp_path) as session:
        assert session.install(flow, path) == 6  # 3 switches x 2 directions
        flows = session.dump_flows()
        for sw in ("leaf1", "spine2", "leaf3"):
            section = flows.split(f"--- {sw} ")[1].split("---")[0]
            assert f"nw_src={flow.src_ip},nw_dst={flow.dst_ip}" in section
        assert f"nw_src={flow.src_ip}" not in flows.split("--- spine1 ")[1].split("---")[0]

        start_servers(session.net, [flow])
        spines = ["spine1", "spine2"]
        pcap = tmp_path / "capture.pcapng"
        os.chmod(tmp_path, 0o777)  # dumpcap may drop privileges before writing
        proc = capture(spine_interfaces(mapping, spines), 4, pcap)
        results = run_traffic(session.net, [flow], {0: 1_000_000}, 3.0, (1.0, 3.0))
        proc.wait(timeout=30)

        assert results[0].error is None and results[0].received_bytes > 0
        (r,) = check(read_counts(pcap), [(0, flow.src_ip, flow.dst_ip, path)], mapping, spines)
        assert r.ok, r
        assert set(r.seen) == {"spine2-eth1", "spine2-eth3"}
