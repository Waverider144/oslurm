import json
import tempfile
import unittest
from pathlib import Path

from oslurm.orbit_benchmark import run_benchmark
from oslurm.power import PowerConfig, project_soc
from oslurm.thermal import ThermalConfig, project_temperature
from oslurm.telemetry import NodeTelemetry
from oslurm.satellite.orbit_agent import OrbitAutonomy
from oslurm.satellite.decisions import SchedulingDecisionType
from oslurm.network.checkpoint import CheckpointNetwork
from tests.test_checkpoint_network import ephemeris


class TelemetryTests(unittest.TestCase):
    def test_integrates_actual_load_and_eclipse_on_one_clock(self):
        data = ephemeris()
        data["samples"] = [s for s in data["samples"] if not s["node_id"].startswith("RELAY-")]
        emitted = []
        telemetry = NodeTelemetry(data, lambda *args, **kwargs: emitted.append((args, kwargs)))
        telemetry.advance(60, "sat001")
        expected_soc = project_soc(0.70, 60, True, PowerConfig())["ending_soc"]
        expected_temp = project_temperature(42, 60, True, ThermalConfig())["ending_temperature_c"]
        self.assertAlmostEqual(telemetry.state["sat001"]["soc"], expected_soc)
        self.assertAlmostEqual(telemetry.state["sat001"]["temperature_c"], expected_temp)
        telemetry.advance(120, "sat001")
        self.assertLess(telemetry.state["sat001"]["soc"], expected_soc)
        self.assertNotEqual(telemetry.state["sat001"], telemetry.state["sat002"])
        self.assertTrue(all(0 <= payload["soc"] <= 1 for _, payload in emitted))
        self.assertEqual(emitted[0][1]["telemetry_source"], "analytic_power_thermal")

    def test_forecast_does_not_mutate_current_telemetry(self):
        data = ephemeris()
        telemetry = NodeTelemetry(data)
        before = dict(telemetry.state["sat001"])
        telemetry.forecast("sat001", 180)
        self.assertEqual(telemetry.now_s, 0)
        self.assertEqual(telemetry.state["sat001"], before)
        with self.assertRaises(ValueError):
            telemetry.advance(-1)


class OrbitAgentTests(unittest.TestCase):
    def setUp(self):
        data = ephemeris()
        self.network = CheckpointNetwork(data)
        compute = {"samples": [s for s in data["samples"] if not s["node_id"].startswith("RELAY-")]}
        self.telemetry = NodeTelemetry(compute, power=PowerConfig(initial_soc=0.42))
        self.telemetry.advance(60, "sat001")
        self.records = []

    def agent(self, until=240):
        return OrbitAutonomy(self.telemetry, lambda *a, **kw: self.records.append((a, kw)),
                             240, disconnect_s=0, authority_until_s=until)

    def test_ground_disconnected_agent_uses_explicit_relay_reachability(self):
        agent = self.agent()
        plan = self.network.plan("CP", "sat001", "sat002", 1000, 60, 240)
        decision, node, intent, payload = agent.decide("sat001", 60, {"sat002": plan}, 1)
        self.assertEqual(decision.decision_type, SchedulingDecisionType.OFFER_REMOTE)
        self.assertEqual(node, "sat002")
        self.assertFalse(payload["ground_connected"])
        self.assertEqual(agent.context("sat001", 60).self_state.links, [])
        self.assertEqual(payload["selected_metrics"]["migration_cost"], plan.predicted_finish_s - 60)
        self.assertTrue(agent.negotiate("sat001", node, 60, plan, intent, 1000, 1))
        self.assertEqual(agent.metrics()["ground_dependent_decisions"], 0)
        self.assertEqual(agent.metrics()["committed_handoffs"], 1)

    def test_expired_authority_does_not_commit_a_handoff(self):
        agent = self.agent(until=10)
        plan = self.network.plan("CP", "sat001", "sat002", 1000, 60, 240)
        decision, node, _, payload = agent.decide("sat001", 60, {"sat002": plan}, 1)
        self.assertEqual(decision.decision_type, SchedulingDecisionType.REJECT)
        self.assertEqual(node, "sat001")
        self.assertEqual(payload["decision_rule"], "AUTHORITY_CHECK")
        self.assertEqual(agent.metrics()["committed_handoffs"], 0)

    def test_unreachable_peer_is_not_advertised_as_direct_neighbor(self):
        decision, node, _, _ = self.agent().decide("sat001", 60, {}, 1)
        self.assertNotEqual(decision.decision_type, SchedulingDecisionType.OFFER_REMOTE)
        self.assertEqual(node, "sat001")

    def test_unhealthy_compute_is_paused_and_trace_has_model_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_benchmark(root, ephemeris=ephemeris(), dimension=128,
                                   initial_soc=0.1, initial_temperature_c=85, policy="autonomous")
            trace = json.loads((root / "profiles" / result["run_id"] / "execution-trace.json").read_text())
        self.assertFalse(result["converged"])
        self.assertEqual(result["iteration"], 0)
        states = [e for e in trace["events"] if e["header"]["event_type"] == "NODE_OPERATING_SNAPSHOT"]
        self.assertTrue(states)
        self.assertTrue(all(not state["payload"]["compute_active"] for state in states))
        self.assertEqual(trace["telemetry"]["source"], "analytic_power_thermal")


if __name__ == "__main__":
    unittest.main()
