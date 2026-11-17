import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oslurm.axb import ConjugateGradient
from oslurm.joint_execution import execute_measured, run_joint_axb
from oslurm.network.checkpoint import deliver_file, sha256
from oslurm.network.models import TransferIntent
from oslurm.network.runtime import MultiConstellationRuntime


def configured_runtime():
    runtime = MultiConstellationRuntime(Path.cwd())
    runtime.load_constellation("compute", "configs/compute-ai.yaml")
    runtime.load_constellation("comm", "configs/relay-public.yaml")
    runtime.connect("compute-ai", "relay-public")
    return runtime


def trace(root):
    return [json.loads(line) for line in (root / "profiles/test/events.jsonl").read_text().splitlines()]


class JointExecutionTests(unittest.TestCase):
    def run_case(self, root, runtime=None, **kwargs):
        return run_joint_axb(root, dimension=128, run_id="test", runtime=runtime or configured_runtime(),
                             contact_mode="fixtures", transport="local", **kwargs)

    def assert_clean(self, runtime):
        self.assertTrue(all(r.state.value in {"completed", "aborted"} for r in runtime.network.reservations.values()))
        self.assertTrue(all(b.reserved_bytes == 0 for b in runtime.network.buffers.values()))

    def test_real_solve_is_input_gated_and_ground_verified(self):
        runtime = configured_runtime()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual_execute = execute_measured

            def gated(*args):
                input_plan = runtime.last_decision.input_plan
                reservations = [r for r in runtime.network.reservations.values() if r.transfer_id == input_plan.transfer_id]
                self.assertTrue(all(r.state.value == "completed" for r in reservations))
                self.assertEqual(sha256(args[4]), sha256(root / "profiles/test/ground/input.npz"))
                return actual_execute(*args)

            with patch("oslurm.joint_execution.execute_measured", side_effect=gated):
                result = self.run_case(root, runtime)
            self.assertEqual(result["status"], "completed", result)
            self.assertLessEqual(result["ground_relative_residual"], 1e-8)
            self.assertEqual(sha256(Path(result["result_path"])), result["result_sha256"])
            self.assertTrue(ConjugateGradient.load(Path(result["result_path"])).converged)
            events = trace(root)
            times = [e["header"]["simulation_time_ns"] for e in events]
            self.assertEqual(times, sorted(times))
            kinds = [e["header"]["event_type"] for e in events]
            self.assertEqual(kinds.count("JOB_STARTED"), 1)
            self.assertEqual(kinds.count("COMPUTE_COMPLETED"), 1)
            self.assertEqual(kinds.count("MISSION_JOB_COMPLETED"), 1)
            self.assertEqual(kinds.count("SIMULATION_END"), 1)
            self.assertIn("NETWORK_REPLAN", kinds)
            manifest = json.loads((root / "profiles/test/manifest.json").read_text())
            self.assertEqual(manifest["scheduler_policy"], "EARLIEST_FEASIBLE_GROUND_DELIVERY")
            self.assertAlmostEqual(result["actual_compute_finish_s"],
                                   runtime.last_decision.compute_start_s + result["execution_elapsed_s"])
            self.assert_clean(runtime)
            with self.assertRaises(FileExistsError):
                self.run_case(root)

    def test_early_finish_advances_downlink_when_contact_is_open(self):
        runtime = configured_runtime()
        runtime.network.contacts = [replace(c, start_s=10) if c.contact_id in {"SAT003-RELAY-A", "RELAY-A-GROUND"}
                                    else c for c in runtime.network.contacts]
        with TemporaryDirectory() as tmp:
            result = self.run_case(Path(tmp), runtime)
        self.assertEqual(result["status"], "completed", result)
        self.assertLess(result["completion_sim_s"], result["predicted_finish_s"] - 200)
        self.assertGreaterEqual(result["completion_sim_s"], result["actual_compute_finish_s"])
        self.assert_clean(runtime)

    def test_actual_late_completion_moves_to_next_contact_not_stale_window(self):
        runtime = configured_runtime()
        contacts = []
        for contact in runtime.network.contacts:
            if contact.contact_id in {"SAT003-RELAY-A", "RELAY-A-GROUND"}:
                contacts.extend([replace(contact, end_s=300),
                                 replace(contact, contact_id=contact.contact_id + "-LATER", start_s=600, end_s=900)])
            else:
                contacts.append(contact)
        runtime.network.contacts = contacts

        def delayed(*args):
            data, _ = execute_measured(*args)
            return data, 400.0

        with TemporaryDirectory() as tmp, patch("oslurm.joint_execution.execute_measured", side_effect=delayed):
            result = self.run_case(Path(tmp), runtime)
            events = trace(Path(tmp))
        self.assertEqual(result["status"], "completed", result)
        self.assertGreater(result["completion_sim_s"], 600)
        replan = next(e for e in events if e["header"]["event_type"] == "NETWORK_REPLAN")
        self.assertGreater(replan["payload"]["actual_compute_finish_s"], replan["payload"]["previous_finish_s"])
        actual_hops = [r for r in result["reservations"] if r["transfer_id"].endswith("-ACTUAL")]
        self.assertTrue(all(r["hop"]["contact_id"].endswith("-LATER") for r in actual_hops))
        self.assert_clean(runtime)

    def test_no_downlink_after_actual_finish_fails_without_false_completion(self):
        runtime = configured_runtime()

        def delayed(*args):
            data, _ = execute_measured(*args)
            return data, 2000.0

        with TemporaryDirectory() as tmp, patch("oslurm.joint_execution.execute_measured", side_effect=delayed):
            result = self.run_case(Path(tmp), runtime)
            kinds = [e["header"]["event_type"] for e in trace(Path(tmp))]
            self.assertFalse((Path(tmp) / "profiles/test/ground/result.npz").exists())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["converged"])
        self.assertIn("no result window", result["error"])
        self.assertIn("COMPUTE_COMPLETED", kinds)
        self.assertNotIn("MISSION_JOB_COMPLETED", kinds)
        self.assertNotIn("JOB_COMPLETED", kinds)
        self.assert_clean(runtime)

    def test_unconverged_solver_never_sends_result(self):
        runtime = configured_runtime()
        with TemporaryDirectory() as tmp:
            result = self.run_case(Path(tmp), runtime, max_iterations=1)
            kinds = [e["header"]["event_type"] for e in trace(Path(tmp))]
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["converged"])
        self.assertNotIn("COMPUTE_COMPLETED", kinds)
        self.assertNotIn("NETWORK_REPLAN", kinds)
        self.assert_clean(runtime)

    def test_corrupt_input_does_not_launch_worker(self):
        runtime = configured_runtime()

        def corrupt(network, plan, source, destination, **kwargs):
            content = bytearray(source.read_bytes())
            content[-1] ^= 1
            source.write_bytes(content)
            return deliver_file(network, plan, source, destination, **kwargs)

        with TemporaryDirectory() as tmp, patch("oslurm.joint_execution.deliver_file", side_effect=corrupt), \
                patch("oslurm.joint_execution.execute_measured") as worker:
            result = self.run_case(Path(tmp), runtime)
            worker.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertIn("checksum", result["error"])
        self.assert_clean(runtime)

    def test_ground_validation_is_required_for_mission_completion(self):
        runtime = configured_runtime()

        def corrupt_ground(network, plan, source, destination, **kwargs):
            digest = deliver_file(network, plan, source, destination, **kwargs)
            if destination.name == "result.npz":
                state = ConjugateGradient.load(destination)
                state.x[:] = 0
                state.save(destination)
            return digest

        with TemporaryDirectory() as tmp, patch("oslurm.joint_execution.deliver_file", side_effect=corrupt_ground):
            result = self.run_case(Path(tmp), runtime)
            kinds = [e["header"]["event_type"] for e in trace(Path(tmp))]
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("MISSION_JOB_COMPLETED", kinds)
        self.assert_clean(runtime)

    def test_replan_failure_is_atomic_before_caller_cleanup(self):
        runtime = configured_runtime()
        runtime.submit_job("workloads/inference.yaml", None)
        previous = runtime.last_decision.result_plan
        before = {r.reservation_id: r.state for r in runtime.network.reservations.values()}
        intent = TransferIntent("late", previous.hops[0].source, previous.hops[-1].destination,
                                previous.hops[0].reserved_bytes, 3000, 3001)
        self.assertIsNone(runtime.network.replan_transfer(previous, intent, now_s=3000))
        self.assertEqual(before, {r.reservation_id: r.state for r in runtime.network.reservations.values()})

    def test_worker_failure_cleans_speculative_reservations(self):
        runtime = configured_runtime()
        with TemporaryDirectory() as tmp, patch("oslurm.joint_execution.execute_measured", side_effect=RuntimeError("worker failed")):
            result = self.run_case(Path(tmp), runtime)
            kinds = [e["header"]["event_type"] for e in trace(Path(tmp))]
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("COMPUTE_COMPLETED", kinds)
        self.assertNotIn("JOB_COMPLETED", kinds)
        self.assert_clean(runtime)


if __name__ == "__main__":
    unittest.main()
