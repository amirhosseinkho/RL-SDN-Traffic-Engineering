"""Tests for path -> OpenFlow rule translation (app.controller.flow_rules) and FlowManager."""
import pytest

from app.controller import flow_rules
from app.controller.flow_rules import FlowRule, Hop
from app.controller.ryu_controller import FlowManager, TopologyManager

# Spine-leaf as built by the topology generator: spine1 = dpid 101, leaf1 = 201, leaf3 = 203
DPIDS = {"spine1": 101, "spine2": 102, "leaf1": 201, "leaf3": 203}
PORTS = {
    ("h1", "leaf1"): 0, ("leaf1", "h1"): 3,
    ("leaf1", "spine1"): 1, ("spine1", "leaf1"): 1,
    ("leaf1", "spine2"): 2, ("spine2", "leaf1"): 1,
    ("spine1", "leaf3"): 3, ("leaf3", "spine1"): 1,
    ("spine2", "leaf3"): 3, ("leaf3", "spine2"): 2,
    ("leaf3", "h5"): 3, ("h5", "leaf3"): 0,
}
VIA_SPINE1 = ["h1", "leaf1", "spine1", "leaf3", "h5"]
VIA_SPINE2 = ["h1", "leaf1", "spine2", "leaf3", "h5"]


class TestPathHops:
    def test_one_hop_per_switch_in_path_order(self):
        assert flow_rules.path_hops(VIA_SPINE1, DPIDS, PORTS) == [Hop(201, 1), Hop(101, 3), Hop(203, 3)]

    def test_reverse_path_uses_the_other_ports(self):
        hops = flow_rules.path_hops(list(reversed(VIA_SPINE1)), DPIDS, PORTS)
        assert hops == [Hop(203, 1), Hop(101, 1), Hop(201, 3)]

    def test_missing_link_raises_instead_of_skipping(self):
        with pytest.raises(KeyError):
            flow_rules.path_hops(["h1", "leaf1", "leaf3", "h5"], DPIDS, PORTS)

    def test_path_ending_at_a_switch_needs_egress_port(self):
        with pytest.raises(ValueError):
            flow_rules.path_hops(["leaf1", "spine1", "leaf3"], DPIDS, PORTS)
        hops = flow_rules.path_hops(["leaf1", "spine1", "leaf3"], DPIDS, PORTS, egress_port=3)
        assert hops == [Hop(201, 1), Hop(101, 3), Hop(203, 3)]


class TestPathRules:
    def test_egress_switch_first_with_ipv4_match_and_cookie(self):
        hops = flow_rules.path_hops(VIA_SPINE1, DPIDS, PORTS)
        match = flow_rules.ipv4_match("192.168.1.2", "192.168.3.6")
        rules = flow_rules.path_rules(hops, match, flow_rules.flow_cookie(7))
        assert [r.dpid for r in rules] == [203, 101, 201]
        assert all(r.match_dict == {"eth_type": 0x0800, "ipv4_src": "192.168.1.2", "ipv4_dst": "192.168.3.6"} for r in rules)
        assert {r.cookie for r in rules} == {flow_rules.flow_cookie(7)}
        assert all(r.priority == flow_rules.PATH_PRIORITY for r in rules)

    def test_cookies_differ_per_flow_and_direction_and_share_a_namespace(self):
        cookies = {flow_rules.flow_cookie(f, rev) for f in range(16) for rev in (False, True)}
        assert len(cookies) == 32
        assert all(c & flow_rules.COOKIE_NAMESPACE_MASK == flow_rules.COOKIE_BASE for c in cookies)

    def test_ofctl_rest_body_is_permanent(self):
        rule = FlowRule(101, flow_rules.ipv4_match("10.0.0.1", "10.0.0.2"), 3, 100, 5)
        body = rule.to_ofctl_rest()
        assert body["idle_timeout"] == 0 and body["hard_timeout"] == 0
        assert body["actions"] == [{"type": "OUTPUT", "port": 3}]
        assert body["match"]["eth_type"] == 2048


class TestPlanUpdate:
    def _rules(self, path):
        match = flow_rules.ipv4_match("192.168.1.2", "192.168.3.6")
        return flow_rules.path_rules(flow_rules.path_hops(path, DPIDS, PORTS), match, flow_rules.flow_cookie(0))

    def test_unchanged_path_sends_nothing(self):
        assert flow_rules.plan_update(self._rules(VIA_SPINE1), self._rules(VIA_SPINE1)) == ([], [])

    def test_moving_to_the_other_spine(self):
        adds, deletes = flow_rules.plan_update(self._rules(VIA_SPINE1), self._rules(VIA_SPINE2))
        # spine2 gets a rule before the ingress leaf is redirected; leaf3's rule is unchanged
        assert [(r.dpid, r.out_port) for r in adds] == [(102, 3), (201, 2)]
        assert [r.dpid for r in deletes] == [101]

    def test_first_install_adds_all(self):
        adds, deletes = flow_rules.plan_update([], self._rules(VIA_SPINE1))
        assert [r.dpid for r in adds] == [203, 101, 201] and deletes == []


class _Recorder:
    """Stands in for an os-ken/Ryu parser: records constructor arguments."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: (name, args, kwargs)


class _FakeOfproto:
    OFPFC_ADD, OFPFC_DELETE, OFPFC_DELETE_STRICT = 0, 3, 4
    OFPIT_APPLY_ACTIONS = 4
    OFPP_ANY, OFPG_ANY, OFPTT_ALL = 0xFFFFFFFF, 0xFFFFFFFF, 0xFF


class _FakeDatapath:
    ofproto = _FakeOfproto
    ofproto_parser = _Recorder()


class TestFlowModConstruction:
    RULE = FlowRule(101, flow_rules.ipv4_match("192.168.1.2", "192.168.3.6"), 3, 100, flow_rules.flow_cookie(2))

    def test_add_is_permanent_with_cookie_and_output_action(self):
        name, _, kw = flow_rules.to_flowmod(_FakeDatapath(), self.RULE)
        assert name == "OFPFlowMod"
        assert kw["command"] == _FakeOfproto.OFPFC_ADD
        assert (kw["priority"], kw["cookie"], kw["idle_timeout"], kw["hard_timeout"]) == (100, self.RULE.cookie, 0, 0)
        assert kw["match"] == ("OFPMatch", (), self.RULE.match_dict)
        (_, (itype, actions), _), = kw["instructions"]
        assert itype == _FakeOfproto.OFPIT_APPLY_ACTIONS
        assert actions == [("OFPActionOutput", (3,), {})]

    def test_delete_is_strict_and_filtered_by_cookie(self):
        _, _, kw = flow_rules.to_flowmod(_FakeDatapath(), self.RULE, delete=True)
        assert kw["command"] == _FakeOfproto.OFPFC_DELETE_STRICT
        assert kw["cookie_mask"] == flow_rules.COOKIE_MASK_ALL
        assert kw["priority"] == 100

    def test_real_os_ken_flowmod_serializes(self):
        ofproto = pytest.importorskip("os_ken.ofproto.ofproto_v1_3")
        parser = pytest.importorskip("os_ken.ofproto.ofproto_v1_3_parser")

        class Datapath:
            pass

        dp = Datapath()
        dp.ofproto, dp.ofproto_parser, dp.id = ofproto, parser, 101
        msg = flow_rules.to_flowmod(dp, self.RULE)
        msg.set_xid(1)
        msg.serialize()
        parsed = parser.OFPFlowMod.parser(dp, msg.version, msg.msg_type, msg.msg_len, msg.xid, msg.buf)
        assert parsed.match["ipv4_dst"] == "192.168.3.6"
        assert parsed.cookie == self.RULE.cookie and parsed.priority == 100
        assert parsed.instructions[0].actions[0].port == 3


class TestFlowManagerWithRyuTopology:
    """Ryu's rest_topology reports dpids and port numbers as hex strings (checked against Ryu 4.34)."""

    def _topology(self):
        tm = TopologyManager()
        tm._switches = [{"dpid": "%016x" % d} for d in (101, 201, 203)]
        tm._links = [
            {"src": {"dpid": "%016x" % s, "port_no": "%08x" % sp}, "dst": {"dpid": "%016x" % d, "port_no": "%08x" % dp}}
            for s, sp, d, dp in [(201, 1, 101, 1), (101, 1, 201, 1), (101, 3, 203, 1), (203, 1, 101, 3)]
        ]
        tm._build_graph()
        return tm

    def test_hops_use_hex_dpids_and_ports(self):
        tm = self._topology()
        path = tm.get_shortest_path("s%016x" % 201, "s%016x" % 203)
        hops = FlowManager(tm)._hops(path, egress_port=3)
        assert hops == [Hop(201, 1), Hop(101, 3), Hop(203, 3)]
