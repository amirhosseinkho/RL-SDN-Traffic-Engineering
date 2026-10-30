"""Build the Mininet network for an EmulationMapping. Needs root and Mininet."""
from __future__ import annotations

from emulation._compat import import_mininet
from emulation.mapping import IP_PREFIX_LEN, EmulationMapping

import_mininet()

from mininet.link import Link, TCLink  # noqa: E402
from mininet.net import Mininet  # noqa: E402
from mininet.node import OVSSwitch, RemoteController  # noqa: E402
from mininet.topo import Topo  # noqa: E402


class MappedTopo(Topo):
    """Switches, hosts and links exactly as in the mapping (names, dpids, port numbers)."""

    def build(self, mapping: EmulationMapping) -> None:  # type: ignore[override]
        for sw in mapping.switches.values():
            # failMode=secure: without a controller rule a packet is dropped, never flooded
            self.addSwitch(sw.mininet, dpid=sw.dpid_hex, protocols="OpenFlow13", failMode="secure")
        for h in mapping.hosts.values():
            self.addHost(h.mininet, ip=f"{h.ip}/{IP_PREFIX_LEN}", mac=h.mac)
            # Host access links are not modelled by the simulator: no shaping
            self.addLink(h.mininet, mapping.switches[h.switch].mininet, port1=0, port2=h.switch_port, cls=Link)
        for lk in mapping.links:
            self.addLink(
                mapping.switches[lk.src].mininet,
                mapping.switches[lk.dst].mininet,
                port1=lk.src_port,
                port2=lk.dst_port,
                cls=TCLink,
                bw=lk.bandwidth_mbps,
                delay=f"{lk.delay_ms:g}ms",
                max_queue_size=lk.max_queue_pkts,
            )


def build_network(mapping: EmulationMapping, controller_port: int = 6653) -> Mininet:
    net = Mininet(
        topo=MappedTopo(mapping=mapping),
        switch=OVSSwitch,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=True,  # no ARP traffic: path rules match IPv4 only
        build=False,
    )
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=controller_port)
    net.build()
    return net


def start_network(net: Mininet) -> None:
    net.start()
    for h in net.hosts:
        # IPv6 neighbour discovery and MLD would only add dropped noise to the captures
        h.cmd("sysctl -qw net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1")
        # fq enforces each socket's pacing rate (iperf3 --fq-rate, see emulation/traffic.py)
        h.cmd(f"tc qdisc replace dev {h.defaultIntf()} root fq")
