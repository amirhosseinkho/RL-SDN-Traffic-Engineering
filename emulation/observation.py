"""Build the agents' observation from emulated-link measurements.

The measured link features are written into the simulator's own link states and the vector is
produced by SDNRoutingEnv._get_observation(), so the layout, normalization and clipping are the
simulator's by construction: per switch link [utilization, latency/50 ms, loss/5 %, queue],
per flow [demand/200 Mbps, active], then [mean utilization, max utilization, congested share].

The flow features come from the environment's own demands (the unscaled simulator values; the
emulated rates are these times the capacity scale, so the ratio to capacity is the same).
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from app.rl.environment import SDNRoutingEnv

from emulation.measure import LinkFeatures


def apply_measurements(env: SDNRoutingEnv, features: Mapping[tuple[str, str], LinkFeatures]) -> None:
    """Overwrite both directions of every switch link's simulated state with measured values."""
    for (u, v), f in features.items():
        for key in ((u, v), (v, u)):
            ls = env.sim_state.link_states[key]
            ls.utilization = float(np.clip(f.utilization, 0.0, 1.0))
            ls.latency_ms = float(f.latency_ms)
            ls.packet_loss = float(f.packet_loss)
            ls.queue_occupancy = float(np.clip(f.queue_occupancy, 0.0, 1.0))
    missing = {frozenset(k) for k in env.sim_state.link_states} - {frozenset(k) for k in features}
    if missing:
        raise KeyError(f"no measurement for links {sorted(tuple(sorted(m)) for m in missing)}")


def observe(env: SDNRoutingEnv, features: Mapping[tuple[str, str], LinkFeatures]) -> np.ndarray:
    apply_measurements(env, features)
    return env._get_observation()
