import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from oslurm.network.joint import ComputeCandidate, JointComputeNetworkPlanner
from oslurm.network.models import BufferState, ContactWindow, NetworkReservationState, TransferIntent
from oslurm.network.runtime import MultiConstellationRuntime
from oslurm.network.service import NetworkPlanningService
from oslurm.profile.recorder import FlightRecorder
from oslurm.profile.schema import TraceEventType
from oslurm.profile.sinks import InMemoryTraceSink


def runtime():
    instance = MultiConstellationRuntime(Path.cwd())
    instance.load_constellation("compute", "configs/compute-ai.yaml")
    instance.load_constellation("comm", "configs/relay-public.yaml")
    instance.connect("compute-ai", "relay-public")
    return instance


def contact(name, source, destination, start=0, end=100, capacity=10000):
    return ContactWindow(name, source, destination, start, end, 800, capacity,
                         source_terminal="radio0", destination_terminal="radio0")


class JointLifecycleTests(unittest.TestCase):
    def test_atomic_reservation_rolls_back_everything_on_conflict(self):
        network = NetworkPlanningService()
        network.add_contacts([contact("up", "ground", "relay"), contact("forward", "relay", "sat")])
        network.set_buffer("relay", BufferState(1000))
        plan = network.plan_transfer(TransferIntent("one", "ground", "sat", 100, 0, 100))[0]
        conflicting = replace(plan, transfer_id="two")
        with self.assertRaises(ValueError):
            network.reserve_plans([plan, conflicting], now_s=0, commit=True)
        self.assertEqual(network.reservations, {})
        self.assertEqual(network.buffers["relay"].reserved_bytes, 0)
        reservations = network.reserve_plans([plan], now_s=0, commit=True)
        self.assertEqual(reservations[0].reservation_id, "NETRES-0001")

    def test_joint_search_tries_other_input_routes(self):
        network = NetworkPlanningService()
        # Fast input exhausts the conservative byte budget needed by the return
        # path. An alternative input route leaves enough for result delivery.
        network.add_contacts([
            contact("up", "ground", "relay", capacity=150),
            contact("forward", "relay", "sat"),
            contact("direct", "ground", "sat", start=5),
            contact("down", "sat", "ground"),
        ])
        # Reuse the input contact on the result route to force a real capacity
        # conflict, not merely a terminal overlap that can be shifted in time.
        network.set_buffer("relay", BufferState(10000))
        network.set_buffer("ground", BufferState(10000))
        candidate = ComputeCandidate("sat", 1, "ground", "relay", 100, 100)
        decision = JointComputeNetworkPlanner(network).choose("JOB", [candidate], now_s=0, deadline_s=100)
        self.assertEqual(decision.input_plan.hops[0].contact_id, "direct")
        self.assertEqual(network.reservations, {})
        self.assertEqual(network.buffers["relay"].reserved_bytes, 0)
        network.reserve_plans([decision.input_plan, decision.result_plan], now_s=0, commit=True)

    def test_compute_queue_delays_compute_not_just_downlink(self):
        network = NetworkPlanningService()
        network.add_contacts([contact("up", "ground", "sat"), contact("down", "sat", "ground")])
        decision = JointComputeNetworkPlanner(network).choose("JOB", [
            ComputeCandidate("sat", 10, "ground", "ground", 100, 100, available_at_s=30)
        ], now_s=0, deadline_s=100)
        self.assertEqual(decision.compute_start_s, 30)
        self.assertEqual(decision.compute_finish_s, 40)
        self.assertEqual(decision.total_finish_s, 41)

    def test_short_runs_are_causal_idempotent_and_release_buffers(self):
        instance = runtime()
        with TemporaryDirectory() as tmp:
            sink = InMemoryTraceSink()
            recorder = FlightRecorder(root=Path(tmp), sink=sink)
            instance.submit_job("workloads/inference.yaml", recorder)
            decision = instance.last_decision
            instance.run("1s", recorder)
            self.assertEqual(instance.jobs["JOB001"]["state"], "input_pending")
            self.assertNotIn(TraceEventType.MISSION_JOB_COMPLETED, [e.header.event_type for e in sink.events])
            self.assertLessEqual(max(e.header.simulation_time_ns for e in sink.events), 1_000_000_000)
            instance.run(f"{decision.compute_finish_s - 1}s", recorder)
            self.assertEqual(instance.jobs["JOB001"]["state"], "result_pending")
            self.assertNotIn(TraceEventType.MISSION_JOB_COMPLETED, [e.header.event_type for e in sink.events])
            instance.run("1h", recorder)
            self.assertEqual(instance.jobs["JOB001"]["state"], "completed")
            self.assertTrue(all(r.state == NetworkReservationState.COMPLETED for r in instance.network.reservations.values()))
            self.assertTrue(all(b.reserved_bytes == 0 for b in instance.network.buffers.values()))
            count = len(sink.events)
            instance.run("1h", recorder)
            self.assertEqual(len(sink.events), count)
            times = [e.header.simulation_time_ns for e in sink.events]
            self.assertEqual(times, sorted(times))
            complete = [e for e in sink.events if e.header.event_type == TraceEventType.COMPUTE_COMPLETED]
            self.assertEqual(complete[0].header.simulation_time_ns, int(decision.compute_finish_s * 1e9))
            recorder.close()

    def test_power_and_thermal_constraints_reject_relay_favorite(self):
        for field, value, cause in [("predicted_min_soc", 0.2, "POWER_RESERVE"),
                                    ("predicted_max_temperature_c", 80, "THERMAL_LIMIT")]:
            with self.subTest(field=field):
                instance = runtime()
                instance.compute_profiles["compute:SAT003"][field] = value
                instance.submit_job("workloads/inference.yaml", None)
                self.assertEqual(instance.last_decision.selected_node, "compute:SAT002")
                report = next(r for r in instance.last_decision.candidate_reports if r["node_id"] == "compute:SAT003")
                self.assertEqual(report["rejection_causes"], [cause])

    def test_optimistic_prediction_cannot_override_unsafe_current_state(self):
        instance = runtime()
        instance.compute_profiles["compute:SAT003"].update({"soc": 0.2, "predicted_min_soc": 0.8,
            "temperature_c": 80, "predicted_max_temperature_c": 20})
        instance.submit_job("workloads/inference.yaml", None)
        report = next(r for r in instance.last_decision.candidate_reports if r["node_id"] == "compute:SAT003")
        self.assertEqual(set(report["rejection_causes"]), {"POWER_RESERVE", "THERMAL_LIMIT"})

    def test_failed_job_does_not_leak_and_duplicate_is_rejected(self):
        instance = runtime()
        instance.network.contacts = [c for c in instance.network.contacts if c.source == "ground:MISSION-CONTROL"]
        with self.assertRaises(RuntimeError):
            instance.submit_job("workloads/inference.yaml", None)
        self.assertFalse(instance.network.reservations)
        self.assertFalse(instance.jobs)
        self.assertFalse(instance._pending_events)
        instance = runtime()
        instance.submit_job("workloads/inference.yaml", None)
        reservations = len(instance.network.reservations)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            instance.submit_job("workloads/inference.yaml", None)
        self.assertEqual(len(instance.network.reservations), reservations)

    def test_two_jobs_keep_compute_and_radio_reservations_separate(self):
        instance = runtime()
        instance.submit_job("workloads/inference.yaml", None)
        first = instance.last_decision
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "second.yaml"
            path.write_text("job_id: JOB002\ninput_bytes: 24000000\nresult_bytes: 8000000\ndeadline: 2h\n")
            instance.submit_job(str(path), None)
        second = instance.last_decision
        if first.selected_node == second.selected_node:
            self.assertGreaterEqual(second.compute_start_s, first.compute_finish_s)
        contacts = {c.contact_id: c for c in instance.network.contacts}
        reservations = list(instance.network.reservations.values())
        for i, left in enumerate(reservations):
            a = contacts[left.hop.contact_id]
            terminals = {(a.source, a.source_terminal), (a.destination, a.destination_terminal)}
            for right in reservations[i + 1:]:
                b = contacts[right.hop.contact_id]
                if terminals.intersection({(b.source, b.source_terminal), (b.destination, b.destination_terminal)}):
                    self.assertTrue(left.hop.end_s <= right.hop.start_s or right.hop.end_s <= left.hop.start_s)
        instance.run("1h", None)
        self.assertTrue(all(j["state"] == "completed" for j in instance.jobs.values()))

    def test_standalone_transfer_really_reserves_bandwidth(self):
        instance = runtime()
        instance.transfer_submit(["ground:MISSION-CONTROL", "compute:SAT003", "24000000"], None)
        self.assertTrue(instance.network.reservations)
        instance.run("2h", None)
        self.assertTrue(all(r.state == NetworkReservationState.COMPLETED for r in instance.network.reservations.values()))

    def test_invalid_inputs_and_resource_profiles_fail_closed(self):
        instance = runtime()
        instance.compute_profiles["compute:SAT003"]["soc"] = float("nan")
        with self.assertRaises(ValueError):
            instance.submit_job("workloads/inference.yaml", None)
        self.assertFalse(instance.network.reservations)
        for duration in ("-1s", "nan", "inf"):
            with self.assertRaises(ValueError):
                instance.run(duration, None)
        self.assertEqual(instance.now_s, 0)
        with self.assertRaises(FileNotFoundError):
            instance.load_constellation("comm", "/missing/constellation.yaml")

    def test_downlink_wait_is_not_counted_as_compute(self):
        network = NetworkPlanningService()
        network.add_contacts([contact("up", "ground", "sat"), contact("down", "sat", "ground", start=50)])
        decision = JointComputeNetworkPlanner(network).choose("JOB", [
            ComputeCandidate("sat", 10, "ground", "ground", 100, 100)
        ], now_s=0, deadline_s=100)
        self.assertEqual(decision.compute_finish_s, 11)
        self.assertEqual(decision.result_plan.hops[0].start_s, 50)
        self.assertEqual(decision.total_finish_s, 51)

    def test_network_change_metric_is_not_always_true(self):
        instance = runtime()
        instance.compute_profiles["compute:SAT003"]["compute_time_s"] = 10
        with TemporaryDirectory() as tmp:
            sink = InMemoryTraceSink()
            recorder = FlightRecorder(root=Path(tmp), sink=sink)
            instance.submit_job("workloads/inference.yaml", recorder)
            event = next(e for e in sink.events if e.header.event_type == TraceEventType.JOINT_PLANNER_DECISION)
            self.assertFalse(event.payload["network_changed_compute_placement"])
            self.assertGreater(event.payload["cost"]["wall_time_ns"], 0)
            recorder.close()

    def test_cli_job_explanation_exposes_all_compute_candidates(self):
        from oslurm.cli import OslurmCli
        cli = OslurmCli(Path.cwd())
        cli.network = runtime()
        cli.network.submit_job("workloads/inference.yaml", None)
        self.assertIn("input_pending", cli.execute("show jobs"))
        report = json.loads(cli.execute("scheduler explain job JOB001"))
        self.assertEqual(len(report["candidates"]), 4)
        self.assertEqual(report["compute_only_node"], "compute:SAT001")
        self.assertEqual(report["selected_node"], "compute:SAT003")


if __name__ == "__main__":
    unittest.main()
