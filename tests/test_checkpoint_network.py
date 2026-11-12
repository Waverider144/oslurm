import json
import tempfile
import unittest
from pathlib import Path

from oslurm.network.checkpoint import CheckpointNetwork, sha256
from oslurm.network.models import BufferState, ContactWindow, TransferIntent
from oslurm.network.service import NetworkPlanningService
from oslurm.orbit_benchmark import run_benchmark
from oslurm.profile.analysis import ProfileAnalyzer


def ephemeris(relay=True):
    states = {"sat001": ([7_000_000, 0, 0], [0, 7500, 0]),
              "sat002": ([0, 7_000_000, 0], [-7500, 0, 0])}
    if relay:
        states["RELAY-A"] = ([28_000_000, 28_000_000, 0], [-2000, 2000, 0])
    return {"samples": [
        {"node_id": node, "timestamp_ms": seconds * 1000, "position_eci_m": r,
         "velocity_eci_mps": v, "in_sunlight": node != "sat001" or seconds < 60}
        for seconds in (0, 60, 120, 180, 240) for node, (r, v) in states.items()],
        "events": [{"node_id": "sat001", "timestamp_ms": 60000, "type": "ECLIPSE_ENTRY"}]}


class CheckpointNetworkTests(unittest.TestCase):
    def test_real_size_two_hops_and_restore_gate(self):
        network = CheckpointNetwork(ephemeris(), bandwidth_cap_bps=1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sender.npz"
            target = Path(tmp) / "receiver.npz"
            source.write_bytes(b"checkpoint" * 1024)
            plan = network.plan("CP1", "sat001", "sat002", source.stat().st_size, 60, 240)
            self.assertIsNotNone(plan)
            self.assertEqual(len(plan.hops), 2)
            self.assertEqual(plan.hops[0].destination, "RELAY-A")
            self.assertTrue(all(h.reserved_bytes == source.stat().st_size for h in plan.hops))
            self.assertGreater(plan.predicted_finish_s, 68)  # Two conservative acquisitions alone take 8s.
            reservations = network.reserve(plan, 60)
            self.assertEqual(network.network.buffers["RELAY-A"].reserved_bytes, source.stat().st_size)
            with self.assertRaises(ValueError):
                network.deliver(plan, source, target, now_s=plan.predicted_finish_s - 0.1)
            self.assertFalse(target.exists())
            digest = network.deliver(plan, source, target, now_s=plan.predicted_finish_s)
            self.assertEqual(digest, sha256(target))
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(network.network.buffers["RELAY-A"].reserved_bytes, 0)
            self.assertTrue(all(r.state.value == "completed" for r in reservations))

    def test_bigger_checkpoints_and_slower_links_cost_more(self):
        fast = CheckpointNetwork(ephemeris(), bandwidth_cap_bps=1_000_000)
        slow = CheckpointNetwork(ephemeris(), bandwidth_cap_bps=100_000)
        a = fast.plan("a", "sat001", "sat002", 100_000, 0, 240)
        b = fast.plan("b", "sat001", "sat002", 1_000_000, 0, 240)
        c = slow.plan("c", "sat001", "sat002", 100_000, 0, 240)
        self.assertLess(a.predicted_finish_s, b.predicted_finish_s)
        self.assertLess(a.predicted_finish_s, c.predicted_finish_s)

    def test_no_earth_penetration_no_buffer_no_deadline_extension(self):
        blocked = CheckpointNetwork(ephemeris(relay=False))
        self.assertIsNone(blocked.plan("a", "sat001", "sat002", 10, 0, 240))
        no_buffer = CheckpointNetwork(ephemeris(), relay_buffer_bytes=0)
        self.assertIsNone(no_buffer.plan("b", "sat001", "sat002", 10, 0, 240))
        bounded = CheckpointNetwork(ephemeris())
        self.assertIsNone(bounded.plan("c", "sat001", "sat002", 10, 238, 240))
        self.assertTrue(all(c.end_s <= 240 for c in bounded.network.contacts))

    def test_competing_transfer_and_atomic_stale_reservation(self):
        network = CheckpointNetwork(ephemeris(), bandwidth_cap_bps=1_000_000)
        first = network.plan("first", "sat001", "sat002", 1_000_000, 0, 240)
        stale = network.plan("stale", "sat001", "sat002", 1_000_000, 0, 240)
        network.reserve(first, 0)
        before = len(network.network.reservations)
        buffer_before = network.network.buffers["RELAY-A"].reserved_bytes
        with self.assertRaises(ValueError):
            network.reserve(stale, 0)
        self.assertEqual(before, len(network.network.reservations))
        self.assertEqual(buffer_before, network.network.buffers["RELAY-A"].reserved_bytes)
        next_plan = network.plan("next", "sat001", "sat002", 1_000_000, 0, 240)
        self.assertGreaterEqual(next_plan.hops[0].start_s, first.hops[-1].end_s)

    def test_lease_expiry_releases_buffer(self):
        network = CheckpointNetwork(ephemeris())
        plan = network.plan("lease", "sat001", "sat002", 100, 0, 240)
        reservations = network.network.reserve_plan(plan, now_s=0, lease_s=1)
        self.assertGreater(network.network.buffers["RELAY-A"].reserved_bytes, 0)
        network.network.expire(2)
        self.assertEqual(network.network.buffers["RELAY-A"].reserved_bytes, 0)
        with self.assertRaises(ValueError):
            network.network.commit_plan(plan)
        self.assertTrue(all(r.state.value == "expired" for r in reservations))

    def test_checkpoint_size_change_aborts_without_receiver_file(self):
        network = CheckpointNetwork(ephemeris())
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.write_bytes(b"first")
            plan = network.plan("CP", "sat001", "sat002", 5, 0, 240)
            reservations = network.reserve(plan, 0)
            source.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                network.deliver(plan, source, target, now_s=plan.predicted_finish_s)
            self.assertFalse(target.exists())
            self.assertTrue(all(r.state.value == "aborted" for r in reservations))
            self.assertEqual(network.network.buffers["RELAY-A"].reserved_bytes, 0)


class CheckpointExperimentTests(unittest.TestCase):
    def test_trace_order_restore_after_arrival_and_compute_budget_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_benchmark(root, ephemeris=ephemeris(), dimension=16, iteration_rate=0.1, policy="eclipse")
            bundle = json.loads((root / "profiles" / result["run_id"] / "execution-trace.json").read_text())
            self.assertTrue(result["converged"])
            self.assertEqual(result["checkpoint_transfer_count"], 1)
            transfer = bundle["communication"]["transfers"][0]
            self.assertGreater(result["simulated_migration_delay_s"], 8)
            self.assertEqual(transfer["bytes"], (root / "profiles" / result["run_id"] / "checkpoint.npz").stat().st_size)
            restored = next(e for e in bundle["events"] if e["header"]["event_type"] == "JOB_RESTORED")
            self.assertAlmostEqual(restored["header"]["simulation_time_ns"] / 1e9, transfer["finish_s"], places=8)
            receiver = [e for e in bundle["events"] if e["header"]["event_type"] == "JOB_PROGRESS" and e["header"]["node_id"] == "sat002"]
            self.assertTrue(all(e["header"]["simulation_time_ns"] / 1e9 > transfer["finish_s"] for e in receiver))
            # First tick has six iterations; the delivery interval removes at least one receiver iteration.
            self.assertLess(receiver[0]["payload"]["iteration"], 12)
            self.assertTrue(all(r["state"] == "completed" for r in bundle["communication"]["reservations"]))
            analyzer = ProfileAnalyzer(root / "profiles" / result["run_id"])
            self.assertEqual(analyzer.bottleneck_summary()["dominant"], "NETWORK")
            report = analyzer.job_report("AXB001")
            self.assertAlmostEqual(report["breakdown_s"]["NETWORK"], result["simulated_migration_delay_s"], places=8)
            self.assertNotIn("MIGRATION", report["breakdown_s"])

    def test_no_route_defers_migration_instead_of_teleporting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_benchmark(root, ephemeris=ephemeris(False), dimension=128, iteration_rate=0.1, policy="eclipse")
            bundle = json.loads((root / "profiles" / result["run_id"] / "execution-trace.json").read_text())
            self.assertEqual(result["migrations"], 0)
            self.assertEqual(result["checkpoint_transfer_count"], 0)
            self.assertFalse(any(e["header"]["event_type"] == "JOB_RESTORED" for e in bundle["events"]))
            self.assertTrue(any(e["payload"].get("trigger") == "NO_CHECKPOINT_ROUTE" for e in bundle["events"]))


if __name__ == "__main__":
    unittest.main()
