"""Checking captured packets against installed paths."""
from collections import Counter

import pytest

from emulation.mapping import build_mapping, experiment_topology
from emulation.verify_paths import (
    check,
    expected_interfaces,
    parse_fields,
    spine_interfaces,
)

SPINES = ["spine1", "spine2"]


@pytest.fixture(scope="module")
def mapping():
    return build_mapping(experiment_topology(), capacity_scale=0.05)


def test_spine_interfaces(mapping):
    assert spine_interfaces(mapping, SPINES) == [f"spine{s}-eth{p}" for s in (1, 2) for p in (1, 2, 3, 4)]


def test_expected_interfaces(mapping):
    assert expected_interfaces(["h1", "leaf1", "spine1", "leaf3", "h5"], mapping, SPINES) == {"spine1-eth1", "spine1-eth3"}
    detour = ["h2", "leaf1", "spine1", "leaf2", "spine2", "leaf3", "h6"]
    assert expected_interfaces(detour, mapping, SPINES) == {"spine1-eth1", "spine1-eth2", "spine2-eth2", "spine2-eth3"}
    assert expected_interfaces(["h1", "leaf1", "h2"], mapping, SPINES) == set()


def test_parse_fields_ignores_incomplete_lines():
    lines = ["spine1-eth1\t10.0.0.1\t10.0.0.2", "spine1-eth1\t10.0.0.1\t10.0.0.2", "spine1-eth3\t\t", "garbage"]
    assert parse_fields(lines) == Counter({("spine1-eth1", "10.0.0.1", "10.0.0.2"): 2})


def test_check_ok_unexpected_and_missing(mapping):
    path = ["h1", "leaf1", "spine1", "leaf3", "h5"]
    a, b = "192.168.1.2", "192.168.3.6"
    good = {("spine1-eth1", a, b): 50, ("spine1-eth3", a, b): 50, ("spine1-eth3", b, a): 5}
    (r,) = check(good, [(0, a, b, path)], mapping, SPINES)
    assert r.ok and r.seen == {"spine1-eth1": 50, "spine1-eth3": 55}

    leaked = {**good, ("spine2-eth1", a, b): 3}
    (r,) = check(leaked, [(0, a, b, path)], mapping, SPINES)
    assert not r.ok and r.unexpected == {"spine2-eth1": 3}

    # only replies on the egress interface: the forward path is not confirmed there
    partial = {("spine1-eth1", a, b): 50, ("spine1-eth3", b, a): 5}
    (r,) = check(partial, [(0, a, b, path)], mapping, SPINES)
    assert not r.ok and r.missing == ["spine1-eth3"]
