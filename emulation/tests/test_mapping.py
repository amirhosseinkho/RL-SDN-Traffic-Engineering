"""The simulator -> Mininet mapping: names, dpids, ports and capacities."""
import pytest

from emulation.mapping import build_mapping, experiment_topology


@pytest.fixture(scope="module")
def topo():
    return experiment_topology()


@pytest.fixture(scope="module")
def mapping(topo):
    return build_mapping(topo, capacity_scale=0.05)


def test_switches_keep_names_and_generator_dpids(mapping, topo):
    assert {s.name: s.dpid for s in topo.switches} == mapping.dpids
    assert mapping.switches["spine1"].dpid_hex == "0000000000000065"
    # Mininet would derive dpid 1 for both spine1 and leaf1 from their names; the mapping must not
    assert len(set(mapping.dpids.values())) == 6


def test_every_switch_link_has_matching_ports_both_ways(mapping, topo):
    ports = mapping.ports
    assert len(mapping.links) == 8  # 2 spines x 4 leaves
    for lk in mapping.links:
        assert ports[(lk.src, lk.dst)] == lk.src_port and ports[(lk.dst, lk.src)] == lk.dst_port
        assert lk.src_intf == f"{lk.src}-eth{lk.src_port}"
    # spine i <-> leaf j uses spine port j and leaf port i (generator's port order)
    assert mapping.intf("spine1", "leaf3") == "spine1-eth3"
    assert mapping.intf("leaf3", "spine2") == "leaf3-eth2"


def test_ports_are_unique_per_switch(mapping):
    seen = {}
    for (node, _), port in mapping.ports.items():
        if node in mapping.switches:
            assert port not in seen.setdefault(node, set())
            seen[node].add(port)
    assert seen["leaf1"] == {1, 2, 3, 4}  # two spines, two hosts


def test_hosts_attach_where_the_generator_put_them(mapping, topo):
    for h in topo.hosts:
        hm = mapping.hosts[h.name]
        assert (hm.switch, hm.switch_port, hm.ip, hm.mac) == (h.connected_switch, h.port, h.ip, h.mac)
        assert mapping.ports[(hm.switch, h.name)] == h.port


def test_capacity_is_scaled_and_delay_kept(mapping):
    for lk in mapping.links:
        assert lk.sim_bandwidth_mbps == 200.0
        assert lk.bandwidth_mbps == pytest.approx(10.0)
        assert lk.delay_ms == 5.0


def test_every_simulator_path_translates_to_hops(mapping, topo):
    from app.controller.flow_rules import path_hops
    from app.rl.environment import SDNRoutingEnv

    env = SDNRoutingEnv(topo)
    for (src, dst), paths in env._paths.items():
        for path in paths:
            hops = path_hops(path, mapping.dpids, mapping.ports)
            assert len(hops) == sum(1 for n in path if n in mapping.switches)


def test_to_dict_is_json_serializable(mapping, tmp_path):
    import json

    mapping.write(tmp_path / "mapping.json")
    data = json.loads((tmp_path / "mapping.json").read_text())
    assert data["switches"]["leaf1"]["dpid"] == 201 and data["capacity_scale"] == 0.05


def test_invalid_scale_rejected(topo):
    with pytest.raises(ValueError):
        build_mapping(topo, capacity_scale=0)
