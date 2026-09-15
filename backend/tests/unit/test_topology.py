"""Unit tests for topology generation."""
import pytest
from app.database.models import TopologyType
from app.database.schemas import TopologyConfig
from app.topology.generator import TopologyGenerator


@pytest.fixture
def generator() -> TopologyGenerator:
    return TopologyGenerator()


def test_linear_topology_switch_count(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(topology_type=TopologyType.LINEAR, num_switches=4, num_hosts=4, name="test")
    topo = generator.generate(cfg)
    assert len(topo.switches) == 4


def test_linear_topology_host_count(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(topology_type=TopologyType.LINEAR, num_switches=4, num_hosts=6, name="test")
    topo = generator.generate(cfg)
    assert len(topo.hosts) == 6


def test_linear_topology_connectivity(generator: TopologyGenerator) -> None:
    import networkx as nx
    cfg = TopologyConfig(topology_type=TopologyType.LINEAR, num_switches=4, num_hosts=4, name="test")
    topo = generator.generate(cfg)
    assert nx.is_connected(topo.graph)


def test_spine_leaf_topology(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(
        topology_type=TopologyType.SPINE_LEAF,
        num_switches=6,
        num_hosts=8,
        num_spine=2,
        num_leaf=4,
        name="test",
    )
    topo = generator.generate(cfg)
    spine_switches = [s for s in topo.switches if "spine" in s.name]
    leaf_switches = [s for s in topo.switches if "leaf" in s.name]
    assert len(spine_switches) == 2
    assert len(leaf_switches) == 4


def test_fat_tree_topology(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(
        topology_type=TopologyType.FAT_TREE, num_switches=20, num_hosts=16, k=4, name="test"
    )
    topo = generator.generate(cfg)
    core_switches = [s for s in topo.switches if "core" in s.name]
    assert len(core_switches) == 4  # (k/2)^2


def test_tree_topology(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(
        topology_type=TopologyType.TREE, num_switches=7, num_hosts=8, depth=2, fanout=2, name="test"
    )
    topo = generator.generate(cfg)
    assert len(topo.switches) >= 3


def test_topology_to_dict(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(topology_type=TopologyType.LINEAR, num_switches=3, num_hosts=3, name="test")
    topo = generator.generate(cfg)
    d = topo.to_dict()
    assert "switches" in d
    assert "hosts" in d
    assert "links" in d


def test_topology_graph_data(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(topology_type=TopologyType.LINEAR, num_switches=3, num_hosts=3, name="test")
    topo = generator.generate(cfg)
    gd = topo.to_graph_data()
    assert "nodes" in gd
    assert "edges" in gd
    assert len(gd["nodes"]) == 6  # 3 switches + 3 hosts


def test_fat_tree_k_must_be_even(generator: TopologyGenerator) -> None:
    cfg = TopologyConfig(
        topology_type=TopologyType.FAT_TREE, num_switches=10, num_hosts=8, k=3, name="test"
    )
    with pytest.raises(ValueError, match="even"):
        generator.generate(cfg)


def test_custom_topology(generator: TopologyGenerator) -> None:
    custom_data = {
        "switches": [{"name": "s1", "dpid": 1}, {"name": "s2", "dpid": 2}],
        "hosts": [{"name": "h1", "ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "connected_switch": "s1"}],
        "links": [{"src": "s1", "dst": "s2", "bandwidth": 100, "latency": 5, "loss": 0}],
    }
    cfg = TopologyConfig(
        topology_type=TopologyType.CUSTOM,
        num_switches=2,
        num_hosts=1,
        custom_data=custom_data,
        name="custom-test",
    )
    topo = generator.generate(cfg)
    assert len(topo.switches) == 2
    assert len(topo.hosts) == 1
