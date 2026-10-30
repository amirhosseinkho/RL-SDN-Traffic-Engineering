"""Traffic in the emulated network: iperf3 UDP flows at given rates, plus pings for RTT.

The parsing functions are pure; the rest runs commands inside Mininet hosts.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

UDP_PAYLOAD_BYTES = 1000
SERVER_BASE_PORT = 5201
CLIENT_BASE_PORT = 40001
PING_INTERVAL_S = 0.2

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
    demanded_bps: float
    sent_bytes: int = 0
    sent_seconds: float = 0.0
    received_bytes: int = 0
    packets: int = 0
    lost_packets: int = 0
    rtts_ms: list[float] = field(default_factory=list)
    pings_sent: int = 0
    pings_received: int = 0
    error: str | None = None

    @property
    def demanded_bytes(self) -> float:
        return self.demanded_bps / 8 * self.sent_seconds

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.lost_packets / self.packets if self.packets else 0.0

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
            "error": self.error,
        }


def parse_iperf3_udp(text: str, result: FlowResult) -> None:
    """Fill sent/received bytes and loss from `iperf3 -u --json` client output."""
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


def parse_ping(text: str, result: FlowResult) -> None:
    result.rtts_ms = [float(m.group(2)) for m in _PING_RTT.finditer(text)]
    summary = _PING_SUMMARY.search(text)
    if summary:
        result.pings_sent, result.pings_received = int(summary.group(1)), int(summary.group(2))


def start_servers(net: Any, flows: list[FlowSpec]) -> list[Any]:
    procs = [
        net[f.dst].popen(["iperf3", "-s", "-p", str(f.server_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in flows
    ]
    time.sleep(0.5)
    return procs


def run_traffic(
    net: Any,
    flows: list[FlowSpec],
    rates_bps: dict[int, float],
    duration_s: float,
    during: Any = None,
) -> dict[int, FlowResult]:
    """Run every flow for duration_s at its rate, with pings alongside. Blocks until done.

    during: optional callable, run while the traffic is flowing (e.g. to take measurements).
    """
    clients, pings = {}, {}
    for f in flows:
        rate = max(1000, int(rates_bps[f.flow_id]))
        clients[f.flow_id] = net[f.src].popen([
            "iperf3", "-c", f.dst_ip, "-u", "-b", str(rate), "-t", f"{duration_s:g}",
            "-p", str(f.server_port), "--cport", str(f.client_port),
            "-l", str(UDP_PAYLOAD_BYTES), "--json",
        ])
        pings[f.flow_id] = net[f.src].popen([
            "ping", "-n", "-i", str(PING_INTERVAL_S), "-w", f"{duration_s:g}", f.dst_ip,
        ])
    if during is not None:
        during()
    results = {}
    for f in flows:
        r = FlowResult(f.flow_id, float(rates_bps[f.flow_id]))
        out, _ = clients[f.flow_id].communicate(timeout=duration_s + 30)
        parse_iperf3_udp(out.decode(errors="replace") if isinstance(out, bytes) else out, r)
        out, _ = pings[f.flow_id].communicate(timeout=duration_s + 30)
        parse_ping(out.decode(errors="replace") if isinstance(out, bytes) else out, r)
        results[f.flow_id] = r
    return results
