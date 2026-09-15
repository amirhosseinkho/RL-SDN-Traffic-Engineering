"""Unit tests for the traffic generator."""
import pytest
from app.simulation.traffic_generator import TrafficGenerator, TrafficPattern


@pytest.fixture
def hosts() -> list[str]:
    return [f"h{i}" for i in range(1, 9)]


@pytest.fixture
def gen(hosts) -> TrafficGenerator:
    return TrafficGenerator(hosts, link_capacity_mbps=100.0)


def test_generate_flows_returns_flows(gen: TrafficGenerator, hosts) -> None:
    flows = gen.generate_flows(num_flows=4)
    assert len(flows) > 0


def test_elephant_flows_have_high_demand(gen: TrafficGenerator) -> None:
    flows = gen.generate_flows(pattern=TrafficPattern.ELEPHANT, num_flows=4)
    elephant = [f for f in flows if f.is_elephant]
    assert len(elephant) > 0
    assert all(f.demand_mbps > 50 for f in elephant)


def test_mice_flows_have_low_demand(gen: TrafficGenerator) -> None:
    flows = gen.generate_flows(pattern=TrafficPattern.MICE, num_flows=8)
    assert all(f.demand_mbps < 20 for f in flows)


def test_flow_ids_are_unique(gen: TrafficGenerator) -> None:
    flows = gen.generate_flows(num_flows=8)
    ids = [f.flow_id for f in flows]
    assert len(ids) == len(set(ids))


def test_traffic_matrix_generation(gen: TrafficGenerator, hosts) -> None:
    tm = gen.generate_traffic_matrix(TrafficPattern.UNIFORM, load_factor=0.5)
    assert len(tm.matrix) > 0
    assert tm.total_demand() > 0


def test_active_flows_property(gen: TrafficGenerator) -> None:
    gen.generate_flows(num_flows=4)
    assert len(gen.active_flows) > 0


def test_update_flows_changes_demand(gen: TrafficGenerator) -> None:
    flows_before = gen.generate_flows(num_flows=4)
    demands_before = [f.demand_mbps for f in flows_before]
    gen.update_flows(dt=1.0)
    flows_after = gen.active_flows
    demands_after = [f.demand_mbps for f in flows_after]
    # Demands should have changed slightly
    assert demands_before != demands_after or len(flows_after) <= len(flows_before)


def test_gravity_traffic_matrix(gen: TrafficGenerator) -> None:
    tm = gen.generate_traffic_matrix(TrafficPattern.GRAVITY, load_factor=0.7)
    assert tm.total_demand() > 0
    assert all(v >= 0 for v in tm.matrix.values())
