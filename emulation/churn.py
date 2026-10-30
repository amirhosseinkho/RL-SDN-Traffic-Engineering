"""Route churn: OpenFlow rule changes needed to move a flow between paths (both directions).

Counted with the controller's own update plan (app.controller.flow_rules.plan_update), so the
simulator runs and the emulation count churn the same way; in the emulation it equals the
number of FlowMods the controller sends.
"""
from __future__ import annotations

from collections.abc import Sequence

from app.controller import flow_rules

from emulation.mapping import EmulationMapping

_MATCH = flow_rules.ipv4_match("0.0.0.0", "0.0.0.0")  # the match does not affect the count


def _rules(path: Sequence[str] | None, mapping: EmulationMapping) -> list[flow_rules.FlowRule]:
    if not path:
        return []
    return flow_rules.path_rules(flow_rules.path_hops(path, mapping.dpids, mapping.ports), _MATCH, 0)


def rule_changes(old: Sequence[str] | None, new: Sequence[str], mapping: EmulationMapping) -> int:
    total = 0
    for a, b in ((old, new), (list(reversed(old)) if old else None, list(reversed(new)))):
        adds, deletes = flow_rules.plan_update(_rules(a, mapping), _rules(b, mapping))
        total += len(adds) + len(deletes)
    return total
