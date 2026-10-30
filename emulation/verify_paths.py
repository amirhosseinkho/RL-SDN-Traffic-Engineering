"""Check with tshark that every flow's packets cross only the links of its installed path.

Capture on every spine-switch interface (headers only), then count packets per
(interface, IPv4 source, IPv4 destination). A flow between hosts a and b may appear only on
the spine interfaces of its path (forward packets on the forward path, replies on its reverse,
which uses the same links), and every spine interface of the forward path must see the flow.

The parsing and checking functions are pure; capture() and read_counts() need tshark.
"""
from __future__ import annotations

import subprocess
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from emulation.mapping import EmulationMapping

SNAPLEN = 96


def spine_interfaces(mapping: EmulationMapping, spines: Iterable[str]) -> list[str]:
    spines = set(spines)
    return sorted(
        mapping.intf(u, v)
        for lk in mapping.links
        for u, v in ((lk.src, lk.dst), (lk.dst, lk.src))
        if u in spines
    )


def expected_interfaces(path: Sequence[str], mapping: EmulationMapping, spines: Iterable[str]) -> set[str]:
    """Spine interfaces a path crosses (both the ingress and egress interface of each spine)."""
    spines = set(spines)
    intfs = set()
    for u, v in zip(path, path[1:]):
        if u in spines:
            intfs.add(mapping.intf(u, v))
        if v in spines:
            intfs.add(mapping.intf(v, u))
    return intfs


def parse_fields(lines: Iterable[str]) -> Counter[tuple[str, str, str]]:
    """Count packets from `tshark -T fields -e frame.interface_name -e ip.src -e ip.dst` output."""
    counts: Counter[tuple[str, str, str]] = Counter()
    for line in lines:
        parts = line.strip().split("\t")
        if len(parts) == 3 and all(parts):
            counts[(parts[0], parts[1], parts[2])] += 1
    return counts


@dataclass
class FlowCheck:
    flow_id: int
    src_ip: str
    dst_ip: str
    path: list[str]
    expected: list[str]
    seen: dict[str, int]  # interface -> packets of this flow (either direction)
    unexpected: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)  # expected interfaces without forward packets

    @property
    def ok(self) -> bool:
        return not self.unexpected and not self.missing


def check(
    counts: Mapping[tuple[str, str, str], int],
    flows: Sequence[tuple[int, str, str, Sequence[str]]],
    mapping: EmulationMapping,
    spines: Iterable[str],
) -> list[FlowCheck]:
    """flows: (flow_id, src_ip, dst_ip, installed path as node names)."""
    spines = list(spines)
    results = []
    for flow_id, src, dst, path in flows:
        expected = expected_interfaces(path, mapping, spines)
        seen: Counter[str] = Counter()
        forward: Counter[str] = Counter()
        for (intf, s, d), n in counts.items():
            if (s, d) == (src, dst):
                seen[intf] += n
                forward[intf] += n
            elif (s, d) == (dst, src):
                seen[intf] += n
        results.append(
            FlowCheck(
                flow_id=flow_id,
                src_ip=src,
                dst_ip=dst,
                path=list(path),
                expected=sorted(expected),
                seen=dict(sorted(seen.items())),
                unexpected={i: n for i, n in sorted(seen.items()) if i not in expected},
                missing=sorted(i for i in expected if forward[i] == 0),
            )
        )
    return results


def capture(interfaces: Sequence[str], duration_s: float, out: Path) -> subprocess.Popen:
    """Start tshark on the given interfaces (root namespace) for duration_s seconds; IPv4 only."""
    cmd = ["tshark", "-q", "-s", str(SNAPLEN), "-f", "ip", "-a", f"duration:{duration_s:g}", "-w", str(out)]
    for intf in interfaces:
        cmd += ["-i", intf]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    # tshark prints "Capturing on ..." once every interface is open
    deadline = time.time() + 10
    while time.time() < deadline and proc.stderr is not None:
        line = proc.stderr.readline()
        if "Capturing on" in line or not line:
            break
    return proc


def read_counts(pcap: Path) -> Counter[tuple[str, str, str]]:
    out = subprocess.run(
        ["tshark", "-r", str(pcap), "-T", "fields", "-e", "frame.interface_name", "-e", "ip.src", "-e", "ip.dst"],
        capture_output=True, text=True, check=True,
    ).stdout
    return parse_fields(out.splitlines())


def format_report(results: Sequence[FlowCheck]) -> str:
    lines = []
    for r in results:
        status = "OK" if r.ok else "MISMATCH"
        lines.append(f"flow {r.flow_id} {r.src_ip} -> {r.dst_ip} path {'-'.join(r.path)}: {status}")
        lines.append(f"  expected spine interfaces: {', '.join(r.expected) or '(none: same leaf)'}")
        lines.append(f"  packets seen (both directions): {r.seen or '{}'}")
        if r.unexpected:
            lines.append(f"  UNEXPECTED: {r.unexpected}")
        if r.missing:
            lines.append(f"  MISSING forward packets on: {r.missing}")
    n_ok = sum(r.ok for r in results)
    lines.append(f"{n_ok}/{len(results)} flows on their installed path only")
    return "\n".join(lines)
