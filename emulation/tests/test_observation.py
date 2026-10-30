"""The observation built from (synthetic) measurements has the simulator's layout and values."""
import numpy as np
import pytest
from app.rl.environment import SDNRoutingEnv

from emulation.mapping import build_mapping, experiment_topology
from emulation.measure import DirectionStats, link_features, measure_links
from emulation.observation import apply_measurements, observe

LIMIT = 25


@pytest.fixture()
def setup():
    topo = experiment_topology()
    mapping = build_mapping(topo, capacity_scale=0.05, max_queue_pkts=LIMIT)
    env = SDNRoutingEnv(topo, seed=1000)
    env.reset(seed=1000)
    env.step(env.action_space.sample())  # some non-trivial routing and load
    return mapping, env


def _synthetic_counters(mapping, env, window_s=7.0):
    """Port stats and tc samples that a network in the simulator's state would produce.

    For each link, all of the simulated load is sent in the forward direction; the queue and
    loss are put on that direction too.
    """
    ports_a, ports_b, tc_a, tc_b = {}, {}, {}, {}
    for lk in mapping.links:
        ls = env.sim_state.link_states[(lk.src, lk.dst)]
        cap = lk.bandwidth_mbps * 1e6
        delay = lk.delay_ms / 1000
        rate = ls.utilization * cap  # bits/s
        pps = rate / 8 / 1042
        queue_delay_s = (ls.latency_ms - lk.delay_ms) / 1000  # sim: 5 ms x (1 + 3 q)
        for u, v, r, p in ((lk.src, lk.dst, rate, pps), (lk.dst, lk.src, 0.0, 0.0)):
            key = (mapping.switches[u].dpid, mapping.ports[(u, v)])
            ports_a[key] = {"tx_bytes": 0, "tx_packets": 0, "duration_s": 100.0}
            ports_b[key] = {"tx_bytes": r / 8 * window_s, "tx_packets": p * window_s, "duration_s": 100.0 + window_s}
            fwd = r > 0
            sent = int(p * window_s) or 1
            drops = round(sent * ls.packet_loss / 100 / (1 - ls.packet_loss / 100)) if fwd else 0
            q = {
                "qlen": (p * delay + ls.queue_occupancy * LIMIT) if fwd else 0.0,
                "backlog": (r / 8 * delay + queue_delay_s * cap / 8) if fwd else 0.0,
                "delay_s": delay,
            }
            dev = mapping.intf(u, v)
            tc_a[dev] = {**q, "drops": 0, "packets": 0}
            tc_b[dev] = {**q, "drops": drops, "packets": sent}
    return ports_a, ports_b, [(0.0, tc_a), (window_s, tc_b)]


def test_measured_observation_equals_simulator_observation(setup):
    mapping, env = setup
    expected = env._get_observation()
    ports_a, ports_b, tc = _synthetic_counters(mapping, env)
    features = measure_links(mapping, ports_a, ports_b, tc, 0.0, 7.0)
    obs = observe(env, features)
    assert obs.shape == env.observation_space.shape == (8 * 4 + 16 * 2 + 3,)
    assert obs.dtype == np.float32 and obs.min() >= 0 and obs.max() <= 1
    # Utilization and queue are exact; loss is rounded to whole packets
    np.testing.assert_allclose(obs, expected, atol=2e-3)


def test_layout_per_link_then_flows_then_global(setup):
    mapping, env = setup
    fwd = DirectionStats(rate_bps=6e6, rate_pps=6e6 / 8 / 1042, mean_qlen_pkts=0, mean_backlog_bytes=0, drops=0, sent_pkts=100, delay_s=0.005)
    rev = DirectionStats(rate_bps=2e6, rate_pps=2e6 / 8 / 1042, mean_qlen_pkts=0, mean_backlog_bytes=0, drops=0, sent_pkts=100, delay_s=0.005)
    features = {(lk.src, lk.dst): link_features(fwd, rev, 10e6, LIMIT) for lk in mapping.links}
    first = env.switch_links[0]
    features[first] = link_features(
        DirectionStats(10e6, 1200, 1200 * 0.005 + 10, 10e6 / 8 * 0.005 + 12500, 25, 975, 0.005), rev, 10e6, LIMIT
    )
    obs = observe(env, features)
    # first link: utilization capped at 1, latency (5 + 10 ms queueing)/50, loss 2.5 %/5, queue 10/25
    np.testing.assert_allclose(obs[:4], [1.0, 15 / 50, 2.5 / 5, 10 / 25], rtol=1e-5)
    # other links: (6 + 2) / 10 Mbps, no queue
    np.testing.assert_allclose(obs[4:8], [0.8, 5 / 50, 0.0, 0.0], rtol=1e-5)
    # flows: demand / 200 Mbps and active flag, from the simulator's own demands
    flows = env.sim_state.flow_demands
    np.testing.assert_allclose(obs[32:34], [min(1, flows[0].demand_mbps / 200), 1.0], rtol=1e-5)
    # global: mean and max utilization, share of links above 0.8
    np.testing.assert_allclose(obs[-3:], [(1.0 + 7 * 0.8) / 8, 1.0, 1 / 8], rtol=1e-5)


def test_delay_line_is_not_counted_as_queue():
    # 9.6 Mbit/s with 5 ms netem delay keeps about 5.8 packets in the delay line
    pps = 9.6e6 / 8 / 1042
    s = DirectionStats(9.6e6, pps, pps * 0.005, 9.6e6 / 8 * 0.005, 0, 1000, 0.005)
    f = link_features(s, DirectionStats(0, 0, 0, 0, 0, 0, 0.005), 10e6, LIMIT)
    assert f.queue_occupancy == 0 and f.latency_ms == pytest.approx(5.0)


def test_every_link_must_be_measured(setup):
    mapping, env = setup
    s = DirectionStats(0, 0, 0, 0, 0, 0, 0.005)
    features = {(lk.src, lk.dst): link_features(s, s, 10e6, LIMIT) for lk in mapping.links[1:]}
    with pytest.raises(KeyError):
        apply_measurements(env, features)
