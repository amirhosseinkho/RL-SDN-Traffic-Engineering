"""Run one routing policy on the emulated network for a number of epochs.

    sudo <venv>/bin/python -m emulation.runner --policy dqn --model models/seed_0/dqn_model.pt \
        --traffic-seed 1000 --epochs 20 --out experiments/mininet_experiment/runs/dqn_rep0

Each epoch mirrors one SDNRoutingEnv step:
  obs_t = measured link state of epoch t-1 + the flows' demands d_t   (simulator layout)
  a_t   = policy(obs_t)                       -> paths installed through the controller
  traffic d_t x capacity_scale for epoch_seconds (iperf3 UDP + pings), measured
  env.step(a_t)                               -> the simulator's prediction for (a_t, d_t), then d_{t+1}
A warm-up epoch with shortest-path routing and d_0 gives obs_0 (as reset() does in the simulator).
The traffic (flows and demand sequence) depends only on --traffic-seed, not on the policy.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from app.rl.environment import SDNRoutingEnv

from emulation.churn import rule_changes
from emulation.mapping import build_mapping, experiment_topology
from emulation.measure import CpuSampler, TcSampler, measure_links
from emulation.observation import observe
from emulation.policies import POLICIES, make_policy
from emulation.session import EmulationSession
from emulation.traffic import FlowSpec, run_traffic, start_servers
from emulation.verify_paths import (
    capture,
    check,
    format_report,
    read_counts,
    spine_interfaces,
)

WINDOW_START_S = 2.0  # measurement window inside each epoch: [start, epoch_seconds - end]
WINDOW_END_S = 1.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--policy", choices=POLICIES, required=True)
    p.add_argument("--model", type=Path)
    p.add_argument("--traffic-seed", type=int, default=1000)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--epoch-seconds", type=float, default=10.0)
    p.add_argument("--scale", type=float, default=0.05, help="emulated capacity / simulated capacity")
    p.add_argument("--queue", type=int, default=25, help="netem queue limit (packets)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--capture-epoch", type=int, help="capture spine interfaces in this epoch and verify paths")
    p.add_argument("--stress-link", help="degrade this switch link, e.g. spine1-leaf1")
    p.add_argument("--stress-from-epoch", type=int, default=5)
    p.add_argument("--stress-extra-delay-ms", type=float, default=20.0)
    p.add_argument("--stress-loss-pct", type=float, default=2.0)
    return p.parse_args()


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.topo = experiment_topology()
        self.mapping = build_mapping(self.topo, args.scale, args.queue)
        self.env = SDNRoutingEnv(self.topo, seed=args.traffic_seed)
        self.env.reset(seed=args.traffic_seed)
        self.flows = [
            FlowSpec(i, f.src_host, f.dst_host, self.mapping.hosts[f.src_host].ip, self.mapping.hosts[f.dst_host].ip)
            for i, f in enumerate(self.env.sim_state.flow_demands)
        ]
        self.policy = make_policy(args.policy, self.env, [f.five_tuple for f in self.flows], args.traffic_seed, args.model)
        self.paths: dict[int, list[str]] = {}
        self.out: Path = args.out

    def demands(self) -> list[float]:
        """Current simulator demands (Mbps, unscaled)."""
        return [round(f.demand_mbps, 4) for f in self.env.sim_state.flow_demands]

    def rates_bps(self) -> dict[int, float]:
        demands = self.env.sim_state.flow_demands
        return {f.flow_id: demands[f.flow_id].demand_mbps * 1e6 * self.args.scale for f in self.flows}

    def install(self, session: EmulationSession, action: np.ndarray) -> tuple[int, int]:
        """Install the paths chosen by action; returns (FlowMods sent, rule changes predicted)."""
        sent = predicted = 0
        for f in self.flows:
            path = self.env._get_paths(f.src, f.dst)[int(action[f.flow_id]) % self.env.max_paths]
            if path != self.paths.get(f.flow_id):
                predicted += rule_changes(self.paths.get(f.flow_id), path, self.mapping)
                sent += session.install(f, path)
                self.paths[f.flow_id] = path
        return sent, predicted

    def run_epoch(self, session: EmulationSession, tc: TcSampler, epoch: int, verify_tag: str | None = None) -> dict[str, Any]:
        T = self.args.epoch_seconds
        marks: dict[str, Any] = {}
        spines = [s for s in self.mapping.switches if s.startswith("spine")]
        pcap = Path(f"/tmp/emu_capture_{os.getpid()}.pcapng")

        def during() -> None:
            time.sleep(WINDOW_START_S)
            marks["t0"], marks["a"] = time.time(), session.client.port_stats()
            if verify_tag:
                marks["tshark"] = capture(spine_interfaces(self.mapping, spines), 3, pcap)
            time.sleep(T - WINDOW_START_S - WINDOW_END_S)
            marks["t1"], marks["b"] = time.time(), session.client.port_stats()

        start = time.time()
        window = (WINDOW_START_S, T - WINDOW_END_S)
        results = run_traffic(session.net, self.flows, self.rates_bps(), T, window, during=during, alternate=epoch % 2 == 1)
        features = measure_links(self.mapping, marks["a"], marks["b"], tc.samples, marks["t0"], marks["t1"])
        record: dict[str, Any] = {"results": results, "features": features, "t0": marks["t0"], "t1": marks["t1"], "start": start}
        if verify_tag:
            marks["tshark"].wait(timeout=30)
            checks = check(read_counts(pcap), [(f.flow_id, f.src_ip, f.dst_ip, self.paths[f.flow_id]) for f in self.flows], self.mapping, spines)
            (self.out / f"verify_{verify_tag}.txt").write_text(format_report(checks) + "\n")
            record["verified"] = {"ok": sum(c.ok for c in checks), "flows": len(checks), "pcap_bytes": pcap.stat().st_size}
            pcap.unlink()
        return record

    def degrade(self, link: str) -> dict[str, Any]:
        u, v = link.split("-")
        lk = self.mapping.link(u, v)
        delay = lk.delay_ms + self.args.stress_extra_delay_ms
        out = {}
        for a, b in ((u, v), (v, u)):
            intf = self.mapping.intf(a, b)
            cmd = ["tc", "qdisc", "change", "dev", intf, "parent", "5:1", "handle", "10:", "netem",
                   "delay", f"{delay:g}ms", "loss", f"{self.args.stress_loss_pct:g}%", "limit", str(lk.max_queue_pkts)]
            subprocess.run(cmd, check=True)
            out[intf] = {"cmd": " ".join(cmd), "after": subprocess.run(["tc", "-s", "qdisc", "show", "dev", intf], capture_output=True, text=True).stdout}
        return out

    def run(self) -> dict[str, Any]:
        args = self.args
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "args.json").write_text(json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, indent=2))
        epochs_file = open(self.out / "epochs.jsonl", "w")
        cpu, tc = CpuSampler(), TcSampler()
        with EmulationSession(self.mapping, self.out) as session:
            cpu.start()
            tc.start()
            start_servers(session.net, self.flows)
            first = self.mapping.links[0]
            (self.out / "tc_qdisc_start.txt").write_text(session.tc_show(first.src_intf))

            # Warm-up: shortest paths, demands d_0 -> obs_0
            self.install(session, np.zeros(self.env.max_flows, dtype=np.int64))
            demands = self.demands()
            rec = self.run_epoch(session, tc, -1)
            epochs_file.write(json.dumps(self._record(-1, None, rec, 0, 0, None, cpu, demands)) + "\n")

            for t in range(args.epochs):
                obs = observe(self.env, rec["features"])
                action = self.policy.select(self.env, obs)
                sent, predicted = self.install(session, action)
                stress = None
                if args.stress_link and t == args.stress_from_epoch:
                    stress = self.degrade(args.stress_link)
                    (self.out / "stress_tc.json").write_text(json.dumps(stress, indent=2))
                demands = self.demands()
                rec = self.run_epoch(session, tc, t, verify_tag=args.policy if t == args.capture_epoch else None)
                _, _, _, _, info = self.env.step(action)  # simulator's prediction for (a_t, d_t)
                record = self._record(t, action, rec, sent, predicted, info, cpu, demands, obs)
                epochs_file.write(json.dumps(record) + "\n")
                epochs_file.flush()
                print(f"epoch {t:2d} delivered {record['delivered_pct']:5.1f}% (sim {record['sim']['delivered_pct']:5.1f}%) "
                      f"churn {sent:3d} cpu {record['cpu']['mean']:4.1f}% wall {record['wall_s']:.1f}s", flush=True)
            (self.out / "tc_qdisc_end.txt").write_text(session.tc_show(first.src_intf))
            tc.stop()
            cpu.stop()
        epochs_file.close()
        summary = summarize(self.out / "epochs.jsonl")
        subprocess.run(["gzip", "-f", str(self.out / "epochs.jsonl")], check=True)
        summary.update({"policy": args.policy, "traffic_seed": args.traffic_seed, "model": str(args.model) if args.model else None,
                        "capacity_scale": args.scale, "epoch_seconds": args.epoch_seconds})
        (self.out / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    def _record(self, t, action, rec, sent, predicted, info, cpu, demands, obs=None) -> dict[str, Any]:
        results = rec["results"]
        # Delivered and lost traffic inside the measurement window (server-side 1 s intervals)
        demanded = sum(r.window_demanded_bytes for r in results.values())
        received = sum(r.window_received_bytes for r in results.values())
        packets = sum(r.window_packets for r in results.values())
        lost = sum(r.window_lost_packets for r in results.values())
        cpu_window = cpu.window(rec["start"], time.time())
        out = {
            "epoch": t,
            "action": None if action is None else [int(a) for a in action],
            "paths": {str(k): v for k, v in self.paths.items()},
            "flowmods": sent,
            "rule_changes_predicted": predicted,
            "demands_mbps": demands,
            "delivered_pct": 100.0 * received / demanded if demanded else 0.0,
            "loss_pct": 100.0 * lost / packets if packets else 0.0,
            "flows": {str(k): {**r.to_dict(), "rtts_ms": [round(x, 2) for x in r.rtts_ms]} for k, r in results.items()},
            "links": {f"{u}-{v}": f.to_dict() for (u, v), f in rec["features"].items()},
            "cpu": {"mean": float(np.mean(cpu_window)) if cpu_window else 0.0, "max": float(np.max(cpu_window)) if cpu_window else 0.0},
            "wall_s": time.time() - rec["start"],
            "window_s": rec["t1"] - rec["t0"],
        }
        if obs is not None:
            out["obs"] = [round(float(x), 5) for x in obs]
        if info is not None:
            # The simulator's prediction for the same routing and demands, incl. its link state
            states = self.env.sim_state.link_states
            out["sim"] = {
                "delivered_pct": 100.0 * info["delivered_ratio"],
                "mean_path_latency_ms": info["mean_path_latency_ms"],
                "links": {
                    f"{lk.src}-{lk.dst}": [round(x, 5) for x in (states[(lk.src, lk.dst)].utilization, states[(lk.src, lk.dst)].latency_ms,
                                                                  states[(lk.src, lk.dst)].packet_loss, states[(lk.src, lk.dst)].queue_occupancy)]
                    for lk in self.mapping.links
                },
            }
        if "verified" in rec:
            out["verified"] = rec["verified"]
        return out


def summarize(epochs_path: Path) -> dict[str, Any]:
    """Run-level metrics over the policy's epochs (the warm-up epoch is excluded)."""
    text = gzip.decompress(epochs_path.read_bytes()).decode() if epochs_path.suffix == ".gz" else epochs_path.read_text()
    epochs = [json.loads(line) for line in text.splitlines()]
    epochs = [e for e in epochs if e["epoch"] >= 0]
    rtts = [x for e in epochs for f in e["flows"].values() for x in f["rtts_ms"]]
    pings_sent = sum(f["pings_sent"] for e in epochs for f in e["flows"].values())
    pings_recv = sum(f["pings_received"] for e in epochs for f in e["flows"].values())
    packets = sum(f["window_packets"] for e in epochs for f in e["flows"].values())
    lost = sum(f["window_lost_packets"] for e in epochs for f in e["flows"].values())
    errors = sum(1 for e in epochs for f in e["flows"].values() if f["error"])
    obs = [e["obs"] for e in epochs if "obs" in e]
    return {
        "epochs": len(epochs),
        "delivered_pct": float(np.mean([e["delivered_pct"] for e in epochs])),
        "sim_predicted_delivered_pct": float(np.mean([e["sim"]["delivered_pct"] for e in epochs])),
        "sim_predicted_flow_latency_ms": float(np.mean([e["sim"]["mean_path_latency_ms"] for e in epochs])),
        "loss_pct": 100.0 * lost / packets if packets else 0.0,
        "rtt_mean_ms": float(np.mean(rtts)) if rtts else None,
        "rtt_p95_ms": float(np.percentile(rtts, 95)) if rtts else None,
        "ping_loss_pct": 100.0 * (1 - pings_recv / pings_sent) if pings_sent else None,
        "flowmods_per_epoch": float(np.mean([e["flowmods"] for e in epochs])),
        "flowmods_match_prediction": all(e["flowmods"] == e["rule_changes_predicted"] for e in epochs),
        "cpu_mean_pct": float(np.mean([e["cpu"]["mean"] for e in epochs])),
        "cpu_max_pct": float(np.max([e["cpu"]["max"] for e in epochs])),
        "iperf_errors": errors,
        "obs_dim": len(obs[0]) if obs else None,
        "obs_min": float(np.min(obs)) if obs else None,
        "obs_max": float(np.max(obs)) if obs else None,
        "wall_s": float(np.sum([e["wall_s"] for e in epochs])),
        "verified": next((e["verified"] for e in epochs if "verified" in e), None),
    }


def main() -> None:
    summary = Runner(parse_args()).run()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
