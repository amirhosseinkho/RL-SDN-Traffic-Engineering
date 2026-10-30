"""Traffic in the emulated network: iperf3 UDP flows at given rates, plus pings for RTT.

The parsing functions are pure; the rest runs commands inside Mininet hosts.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

UDP_PAYLOAD_BYTES = 1000
# On the wire (and in htb's accounting) each datagram also carries UDP, IPv4 and Ethernet headers
WIRE_BYTES = UDP_PAYLOAD_BYTES + 8 + 20 + 14
PAYLOAD_FRACTION = UDP_PAYLOAD_BYTES / WIRE_BYTES
SOCKET_BUFFER = "32K"  # bounds how far ahead of the pacing iperf3 can queue
SERVER_BASE_PORT = 5201
CLIENT_BASE_PORT = 40001
# Consecutive tests of a flow alternate between two servers, so datagrams still queued when one
# test ends (they drain at the flow's pacing rate) cannot reach the next test's server
ALTERNATE_PORT_OFFSET = 100
PING_INTERVAL_S = 0.2
# iperf3 sets up a UDP test with one datagram and its reply and waits 30 s for the reply; on a
# congested link the datagram can be dropped. All hosts are therefore capped while the clients
# start, so the links are idle during setup, and the cap is lifted after SETUP_S.
SETUP_CAP = "100kbit"
SETUP_S = 1.0
UNCAPPED = "10Gbit"

_PING_RTT = re.compile(r"icmp_seq=(\d+) .*time=([\d.]+) ms")
_PING_SUMMARY = re.compile(r"(\d+) packets transmitted, (\d+) received")


@dataclass(frozen=True)
class FlowSpec:
    flow_id: int
    src: str  # host names
    dst: str
    src_ip: str
    dst_ip: str

    @property
    def server_port(self) -> int:
        return SERVER_BASE_PORT + self.flow_id

    @property
    def client_port(self) -> int:
        return CLIENT_BASE_PORT + self.flow_id

    @property
    def five_tuple(self) -> tuple[str, str, int, int, int]:
        return (self.src_ip, self.dst_ip, 17, self.client_port, self.server_port)


@dataclass
class FlowResult:
    flow_id: int
    demanded_bps: float  # on the wire, headers included (what the link capacity is compared with)
    sent_bytes: int = 0
    sent_seconds: float = 0.0
    received_bytes: int = 0
    packets: int = 0
    lost_packets: int = 0
    rtts_ms: list[float] = field(default_factory=list)
    pings_sent: int = 0
    pings_received: int = 0
    # Receiver side, only the server's 1 s intervals inside the measurement window
    window_seconds: float = 0.0
    window_received_bytes: int = 0
    window_packets: int = 0
    window_lost_packets: int = 0
    error: str | None = None

    @property
    def demanded_bytes(self) -> float:
        """UDP payload the flow should deliver at its demanded wire rate."""
        return self.demanded_bps / 8 * PAYLOAD_FRACTION * self.sent_seconds

    @property
    def window_demanded_bytes(self) -> float:
        return self.demanded_bps / 8 * PAYLOAD_FRACTION * self.window_seconds

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.window_lost_packets / self.window_packets if self.window_packets else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "demanded_bps": self.demanded_bps,
            "sent_bytes": self.sent_bytes,
            "sent_seconds": self.sent_seconds,
            "received_bytes": self.received_bytes,
            "packets": self.packets,
            "lost_packets": self.lost_packets,
            "loss_pct": self.loss_pct,
            "rtts_ms": self.rtts_ms,
            "pings_sent": self.pings_sent,
            "pings_received": self.pings_received,
            "window_seconds": self.window_seconds,
            "window_received_bytes": self.window_received_bytes,
            "window_demanded_bytes": self.window_demanded_bytes,
            "window_packets": self.window_packets,
            "window_lost_packets": self.window_lost_packets,
            "error": self.error,
        }


def parse_iperf3_udp(text: str, result: FlowResult, window: tuple[float, float] | None = None) -> None:
    """Fill result from `iperf3 -u --json --get-server-output` client output.

    window: (start, end) in seconds since the test started; the server's intervals that lie inside
    it give the window_* fields.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        result.error = f"iperf3 output is not JSON: {text[:200]!r}"
        return
    if "error" in data:
        result.error = str(data["error"])
    end = data.get("end", {})
    sent, received = end.get("sum_sent"), end.get("sum_received")
    if not sent or not received:
        result.error = result.error or "iperf3 JSON has no sum_sent/sum_received"
        return
    result.sent_bytes = int(sent["bytes"])
    result.sent_seconds = float(sent["seconds"])
    result.received_bytes = int(received["bytes"])
    result.packets = int(received["packets"])
    result.lost_packets = max(0, int(received["lost_packets"]))
    if window is not None:
        server = data.get("server_output_json") or {}
        for iv in server.get("intervals", []):
            iv = iv["sum"]
            if iv["start"] >= window[0] - 0.05 and iv["end"] <= window[1] + 0.05:
                result.window_seconds += iv["end"] - iv["start"]
                result.window_received_bytes += int(iv["bytes"])
                result.window_packets += int(iv.get("packets", 0))
                result.window_lost_packets += max(0, int(iv.get("lost_packets", 0)))
        if result.window_seconds == 0:
            result.error = result.error or "no server intervals inside the measurement window"


def parse_ping(text: str, result: FlowResult) -> None:
    result.rtts_ms = [float(m.group(2)) for m in _PING_RTT.finditer(text)]
    summary = _PING_SUMMARY.search(text)
    if summary:
        result.pings_sent, result.pings_received = int(summary.group(1)), int(summary.group(2))


def start_servers(net: Any, flows: list[FlowSpec]) -> list[Any]:
    procs = [
        net[f.dst].popen(
            ["iperf3", "-s", "-J", "-p", str(f.server_port + offset)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for f in flows
        for offset in (0, ALTERNATE_PORT_OFFSET)
    ]
    time.sleep(0.5)
    return procs


def _cap_hosts(net: Any, hosts: set[str], rate: str) -> None:
    for name in hosts:
        h = net[name]
        h.cmd(f"tc qdisc change dev {h.defaultIntf()} root fq maxrate {rate}")


def _text(out: Any) -> str:
    return out.decode(errors="replace") if isinstance(out, bytes) else (out or "")


def run_traffic(
    net: Any,
    flows: list[FlowSpec],
    rates_bps: dict[int, float],
    duration_s: float,
    window: tuple[float, float],
    during: Any = None,
    alternate: bool = False,
) -> dict[int, FlowResult]:
    """Run every flow for duration_s at its rate, with pings alongside. Blocks until done.

    Rates are wire rates. The kernel paces each iperf3 socket (fq qdisc on the host interface,
    SO_MAX_PACING_RATE via --fq-rate) and iperf3 itself runs unlimited (-b 0): iperf3 3.16's own
    UDP rate limiting busy-waits at 100% CPU per client, which would saturate the machine.
    The first SETUP_S seconds run capped (see SETUP_CAP); window should start after that.

    window: measurement window (seconds since start) for the window_* fields.
    during: optional callable, run in a thread while the traffic is flowing (e.g. measurements).
    alternate: use the second server of each flow (see ALTERNATE_PORT_OFFSET).
    """
    if window[0] < SETUP_S:
        raise ValueError("the measurement window must start after the setup phase")
    offset = ALTERNATE_PORT_OFFSET if alternate else 0
    sources = {f.src for f in flows}
    _cap_hosts(net, sources, SETUP_CAP)
    worker = threading.Thread(target=during, daemon=True) if during is not None else None
    start = time.time()
    clients = {
        f.flow_id: net[f.src].popen([
            "iperf3", "-c", f.dst_ip, "-u", "-b", "0", "--fq-rate", str(max(1000, int(rates_bps[f.flow_id]))),
            "-w", SOCKET_BUFFER, "-t", f"{duration_s:g}", "-p", str(f.server_port + offset),
            "--cport", str(f.client_port), "-l", str(UDP_PAYLOAD_BYTES), "--json", "--get-server-output",
        ])
        for f in flows
    }
    pings = {
        f.flow_id: net[f.src].popen(["ping", "-n", "-i", str(PING_INTERVAL_S), "-w", f"{duration_s:g}", f.dst_ip])
        for f in flows
    }
    if worker:
        worker.start()
    time.sleep(max(0.0, start + SETUP_S - time.time()))
    _cap_hosts(net, sources, UNCAPPED)

    results = {}
    for f in flows:
        r = FlowResult(f.flow_id, float(rates_bps[f.flow_id]))
        proc = clients[f.flow_id]
        try:
            out, _ = proc.communicate(timeout=max(1.0, start + duration_s + 5 - time.time()))
            parse_iperf3_udp(_text(out), r, window)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            r.error = "iperf3 still running 5 s after the test (UDP setup reply lost?)"
        results[f.flow_id] = r
    if worker:
        worker.join()
    for f in flows:
        out, _ = pings[f.flow_id].communicate(timeout=30)
        parse_ping(_text(out), results[f.flow_id])
    return results
