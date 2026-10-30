"""Measurements of the emulated links, turned into the simulator's per-link features.

Sources, per direction u -> v of a switch link:
- OVS port statistics of u's port towards v (through the controller, every second): bytes and
  packets sent onto the link, with the switch's own port duration as the clock.
- `tc -s -j qdisc show` of the netem qdisc on that interface, sampled every 0.5 s: queue length
  (packets and bytes, which include packets held for the netem delay), drops (queue overflow and
  netem random loss), and the configured delay.

link_features() is pure; the samplers run threads.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from emulation.mapping import EmulationMapping


@dataclass
class DirectionStats:
    """One direction of a link over one measurement window."""

    rate_bps: float  # sent onto the link
    rate_pps: float
    mean_qlen_pkts: float  # netem queue, including packets held for the delay
    mean_backlog_bytes: float
    drops: int
    sent_pkts: int
    delay_s: float  # netem delay currently configured


@dataclass
class LinkFeatures:
    """Simulator link features (LinkState fields) estimated from measurements."""

    utilization: float  # both directions over the per-direction capacity, capped at 1
    latency_ms: float
    packet_loss: float  # percent
    queue_occupancy: float
    directions: dict[str, DirectionStats]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["directions"] = {k: asdict(v) for k, v in self.directions.items()}
        return d


def direction_features(s: DirectionStats, capacity_bps: float, limit_pkts: int) -> tuple[float, float, float]:
    """(queue occupancy, queueing delay in ms, loss %) of one direction.

    The netem queue also holds the packets in flight in its delay line (rate x delay); those are
    not queueing, so they are subtracted.
    """
    queue_pkts = max(0.0, s.mean_qlen_pkts - s.rate_pps * s.delay_s)
    queue_bytes = max(0.0, s.mean_backlog_bytes - s.rate_bps / 8 * s.delay_s)
    occupancy = min(1.0, queue_pkts / limit_pkts) if limit_pkts > 0 else 0.0
    queue_delay_ms = queue_bytes * 8 / capacity_bps * 1000 if capacity_bps > 0 else 0.0
    offered = s.drops + s.sent_pkts
    loss_pct = 100.0 * s.drops / offered if offered else 0.0
    return occupancy, queue_delay_ms, loss_pct


def link_features(fwd: DirectionStats, rev: DirectionStats, capacity_bps: float, limit_pkts: int) -> LinkFeatures:
    """Combine both directions the way the simulator models a link.

    The simulator adds the demand of the flows crossing a link in either direction and divides by
    one capacity; its link state is the same in both directions. Utilization here follows that
    definition (so it reads as the simulator's for the same traffic), although each emulated
    direction has the full capacity. Queue, latency and loss take the worse direction.
    """
    occ_f, qd_f, loss_f = direction_features(fwd, capacity_bps, limit_pkts)
    occ_r, qd_r, loss_r = direction_features(rev, capacity_bps, limit_pkts)
    base_ms = max(fwd.delay_s, rev.delay_s) * 1000
    return LinkFeatures(
        utilization=min(1.0, (fwd.rate_bps + rev.rate_bps) / capacity_bps),
        latency_ms=base_ms + max(qd_f, qd_r),
        packet_loss=max(loss_f, loss_r),
        queue_occupancy=max(occ_f, occ_r),
        directions={"fwd": fwd, "rev": rev},
    )


def port_delta(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[float, float, float]:
    """(bytes/s, packets/s, seconds) sent between two port-stats snapshots of one port."""
    dt = b["duration_s"] - a["duration_s"]
    if dt <= 0:
        return 0.0, 0.0, 0.0
    return (b["tx_bytes"] - a["tx_bytes"]) / dt, (b["tx_packets"] - a["tx_packets"]) / dt, dt


def qdisc_window(samples: Sequence[tuple[float, dict[str, dict[str, Any]]]], dev: str, t0: float, t1: float) -> dict[str, float]:
    """Mean queue and drop/packet deltas of one netem qdisc between t0 and t1."""
    window = [s[dev] for t, s in samples if t0 <= t <= t1 and dev in s]
    if not window:
        return {"qlen": 0.0, "backlog": 0.0, "drops": 0, "packets": 0, "delay_s": 0.0}
    return {
        "qlen": sum(q["qlen"] for q in window) / len(window),
        "backlog": sum(q["backlog"] for q in window) / len(window),
        "drops": window[-1]["drops"] - window[0]["drops"],
        "packets": window[-1]["packets"] - window[0]["packets"],
        "delay_s": window[-1]["delay_s"],
    }


def measure_links(
    mapping: EmulationMapping,
    ports_a: Mapping[tuple[int, int], Mapping[str, Any]],
    ports_b: Mapping[tuple[int, int], Mapping[str, Any]],
    tc_samples: Sequence[tuple[float, dict[str, dict[str, Any]]]],
    t0: float,
    t1: float,
) -> dict[tuple[str, str], LinkFeatures]:
    """Features of every switch link (keyed (src, dst) as in the mapping) over one window."""
    features = {}
    for lk in mapping.links:
        stats = []
        for u, v in ((lk.src, lk.dst), (lk.dst, lk.src)):
            key = (mapping.switches[u].dpid, mapping.ports[(u, v)])
            bps, pps, _ = port_delta(ports_a[key], ports_b[key])
            q = qdisc_window(tc_samples, mapping.intf(u, v), t0, t1)
            stats.append(DirectionStats(bps * 8, pps, q["qlen"], q["backlog"], int(q["drops"]), int(q["packets"]), q["delay_s"] or lk.delay_ms / 1000))
        features[(lk.src, lk.dst)] = link_features(stats[0], stats[1], lk.bandwidth_mbps * 1e6, lk.max_queue_pkts)
    return features


def parse_tc_json(text: str) -> dict[str, dict[str, Any]]:
    """netem qdiscs from `tc -s -j qdisc show`, keyed by device."""
    out = {}
    for q in json.loads(text or "[]"):
        if q.get("kind") != "netem":
            continue
        delay = q.get("options", {}).get("delay", {})
        out[q["dev"]] = {
            "qlen": q.get("qlen", 0),
            "backlog": q.get("backlog", 0),
            "drops": q.get("drops", 0),
            "packets": q.get("packets", 0),
            "delay_s": float(delay.get("delay", 0.0)) if isinstance(delay, dict) else 0.0,
            "loss": q.get("options", {}).get("loss-random", {}).get("loss", 0.0),
        }
    return out


class TcSampler(threading.Thread):
    """Samples every netem qdisc in the root namespace (the switch interfaces) periodically."""

    def __init__(self, interval_s: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.samples: list[tuple[float, dict[str, dict[str, Any]]]] = []
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            t = time.time()
            out = subprocess.run(["tc", "-s", "-j", "qdisc", "show"], capture_output=True, text=True).stdout
            self.samples.append((t, parse_tc_json(out)))
            self.samples = self.samples[-600:]
            self._halt.wait(self.interval_s)

    def stop(self) -> None:
        self._halt.set()


class CpuSampler(threading.Thread):
    """Whole-machine CPU utilization (all cores), from /proc/stat once per second."""

    def __init__(self, interval_s: float = 1.0) -> None:
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.samples: list[tuple[float, float]] = []
        self._halt = threading.Event()

    @staticmethod
    def _read() -> tuple[int, int]:
        with open("/proc/stat") as f:
            values = [int(x) for x in f.readline().split()[1:]]
        idle = values[3] + values[4]  # idle + iowait
        return sum(values), idle

    def run(self) -> None:
        total0, idle0 = self._read()
        while not self._halt.wait(self.interval_s):
            total, idle = self._read()
            if total > total0:
                self.samples.append((time.time(), 100.0 * (1 - (idle - idle0) / (total - total0))))
            total0, idle0 = total, idle

    def window(self, t0: float, t1: float) -> list[float]:
        return [c for t, c in self.samples if t0 <= t <= t1]

    def stop(self) -> None:
        self._halt.set()
