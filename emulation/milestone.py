"""Controller milestone: paths installed through the REST API reach the switches and carry the traffic.

    sudo <venv>/bin/python -m emulation.milestone --out experiments/mininet_experiment/phase1

1. Start the os-ken app and the spine-leaf network; LLDP must discover exactly the mapped links.
2. Install four flows, both directions, on paths taken from the simulator's K shortest paths
   (via spine1, via spine2, a five-switch detour, and a same-leaf flow).
3. Dump the flow tables of every switch.
4. Send 2 s of iperf3 UDP + pings per flow while tshark captures every spine interface; check that
   each flow appears only on its path's interfaces.
5. Move one flow to the other spine (a policy change) and repeat 3 and 4: the old spine's rule must
   be gone and the traffic must follow the new path.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from app.rl.environment import SDNRoutingEnv

from emulation.mapping import build_mapping, experiment_topology
from emulation.session import EmulationSession
from emulation.traffic import FlowSpec, run_traffic, start_servers
from emulation.verify_paths import (
    capture,
    check,
    format_report,
    read_counts,
    spine_interfaces,
)


def pick_paths(env: SDNRoutingEnv) -> dict[tuple[str, str], list[str]]:
    paths = {}
    p15 = env._get_paths("h1", "h5")
    paths[("h1", "h5")] = next(p for p in p15 if "spine1" in p and len(p) == 5)
    p37 = env._get_paths("h3", "h7")
    paths[("h3", "h7")] = next(p for p in p37 if "spine2" in p and len(p) == 5)
    p26 = env._get_paths("h2", "h6")
    paths[("h2", "h6")] = max(p26, key=len)  # detour through two spines
    paths[("h1", "h2")] = env._get_paths("h1", "h2")[0]  # same leaf: no spine
    return paths


def capture_and_check(session: EmulationSession, flows, paths, tag: str, out: Path) -> bool:
    spines = [s for s in session.mapping.switches if s.startswith("spine")]
    intfs = spine_interfaces(session.mapping, spines)
    pcap = Path("/tmp") / f"milestone_{tag}.pcapng"  # tshark (dumpcap) may not write into a home dir as root
    proc = capture(intfs, 4, pcap)
    run_traffic(session.net, flows, {f.flow_id: 1_000_000 for f in flows}, 2.0)
    proc.wait(timeout=30)
    counts = read_counts(pcap)
    results = check(counts, [(f.flow_id, f.src_ip, f.dst_ip, paths[(f.src, f.dst)]) for f in flows], session.mapping, spines)
    report = format_report(results)
    (out / f"verify_{tag}.txt").write_text(report + "\n")
    print(report)
    subprocess.run(["cp", str(pcap), str(out / f"capture_{tag}.pcapng")], check=True)
    return all(r.ok for r in results)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    out = args.out
    topo = experiment_topology()
    mapping = build_mapping(topo, capacity_scale=0.05)
    env = SDNRoutingEnv(topo)
    paths = pick_paths(env)
    flows = [
        FlowSpec(i, s, d, mapping.hosts[s].ip, mapping.hosts[d].ip)
        for i, (s, d) in enumerate(paths)
    ]

    with EmulationSession(mapping, out) as session:
        log = {"flows": [], "path_change": None}
        for f in flows:
            n = session.install(f, paths[(f.src, f.dst)])
            log["flows"].append({"flow_id": f.flow_id, "src": f.src, "dst": f.dst, "path": paths[(f.src, f.dst)], "flowmods": n})
        (out / "dump_flows_initial.txt").write_text(session.dump_flows())
        (out / "tc_spine1-eth1.txt").write_text(session.tc_show("spine1-eth1"))
        start_servers(session.net, flows)
        ok1 = capture_and_check(session, flows, paths, "initial", out)

        # Policy change: h1 -> h5 moves from spine1 to spine2
        new = next(p for p in env._get_paths("h1", "h5") if "spine2" in p and len(p) == 5)
        n = session.install(flows[0], new)
        log["path_change"] = {"flow_id": 0, "old": paths[("h1", "h5")], "new": new, "flowmods": n}
        paths[("h1", "h5")] = new
        (out / "dump_flows_after_change.txt").write_text(session.dump_flows())
        ok2 = capture_and_check(session, flows, paths, "after_change", out)
        log["controller_paths"] = session.client.paths()
        log["verified"] = {"initial": ok1, "after_change": ok2}
        (out / "milestone.json").write_text(json.dumps(log, indent=2))
    print("verified:", log["verified"])


if __name__ == "__main__":
    main()
