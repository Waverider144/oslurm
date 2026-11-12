import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from oslurm.axb import ConjugateGradient, matvec
from oslurm.orbit_benchmark import orbit_period_s, plan_segments, run_benchmark
from oslurm.profile.recorder import FlightRecorder
from oslurm.profile.analysis import ProfileAnalyzer
from oslurm.profile.sinks import InMemoryTraceSink
from providers.gmat.adapter import GMAT_EPOCH_UNIX_MS, mock_leo_ephemeris, parse_gmat_report, write_gmat_script


class ConjugateGradientTests(unittest.TestCase):
    def test_matches_dense_reference_and_checks_true_residual(self):
        solver = ConjugateGradient(48, tolerance=1e-10)
        matrix = np.diag(np.full(48, 2.0001)) + np.diag(-np.ones(47), 1) + np.diag(-np.ones(47), -1)
        result = solver.advance(200)
        self.assertTrue(result["converged"])
        np.testing.assert_allclose(solver.x, np.linalg.solve(matrix, solver.b), atol=1e-9)
        self.assertLess(np.linalg.norm(solver.b - matvec(solver.x)) / np.linalg.norm(solver.b), 1e-10)

    def test_checkpoint_restores_full_krylov_state(self):
        full = ConjugateGradient(256)
        expected = full.advance(80)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.npz"
            interrupted = ConjugateGradient(256)
            interrupted.advance(31)
            interrupted.save(path)
            restored = ConjugateGradient.load(path)
            result = restored.advance(49)
        self.assertEqual(expected["iteration"], result["iteration"])
        np.testing.assert_array_equal(full.x, restored.x)
        np.testing.assert_array_equal(full.p, restored.p)
        self.assertEqual(expected["relative_residual"], result["relative_residual"])

    def test_insufficient_budget_does_not_claim_success(self):
        self.assertFalse(ConjugateGradient(256).advance(1)["converged"])


class FullOrbitBenchmarkTests(unittest.TestCase):
    def test_imported_execution_wall_time_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = FlightRecorder(root=Path(tmp), sink=InMemoryTraceSink())
            event = recorder.emit("JOB_PROGRESS", 1000, wall_time_ns=123456789,
                                  payload={"relative_residual": 0.1})
            recorder.close()
        self.assertEqual(event.header.wall_time_ns, 123456789)

    def test_full_orbit_and_nondefault_sampling_script(self):
        self.assertLess(orbit_period_s(), 5760)
        script = write_gmat_script(Path("orbit.csv"), horizon_s=5760, step_s=30)
        self.assertIn("For i = 1:192", script)
        self.assertIn("sat001.ElapsedSecs = 30", script)
        with self.assertRaises(ValueError):
            write_gmat_script(Path("orbit.csv"), 100, 60)

    def test_report_timestamps_follow_gmat_epoch_not_row_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.csv"
            rows = []
            for offset_s in (0, 30, 90):
                row = [28000 + offset_s / 86400, 6921, 0, 0, 0, 7, 0] * 4
                rows.append(",".join(map(str, row)))
            path.write_text("\n".join(rows))
            result = parse_gmat_report(path)
        self.assertEqual([sample["timestamp_ms"] for sample in result["samples"][::4]],
                         [GMAT_EPOCH_UNIX_MS + seconds * 1000 for seconds in (0, 30, 90)])

    def test_trace_checkpoint_and_result_belong_to_same_run(self):
        ephemeris = mock_leo_ephemeris(5760, 60)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_benchmark(root, ephemeris=ephemeris, dimension=128,
                                   iteration_rate=0.03, run_id="test-axb", checkpoint_transport="shared", policy="eclipse")
            path = root / "profiles" / "test-axb"
            bundle = json.loads((path / "execution-trace.json").read_text())
            events = bundle["events"]
            self.assertTrue(result["converged"])
            self.assertGreater(result["migrations"], 0)
            self.assertEqual(result, bundle["result"])
            self.assertEqual(ephemeris, bundle["ephemeris"])
            times = [event["header"]["simulation_time_ns"] for event in events]
            self.assertEqual(times, sorted(times))
            self.assertEqual(times[-1], 5760_000_000_000)
            self.assertEqual({event["header"]["run_id"] for event in events}, {"test-axb"})
            self.assertEqual(sum(event["header"]["event_type"] == "JOB_COMPLETED" for event in events), 1)
            self.assertTrue(ConjugateGradient.load(path / "checkpoint.npz").converged)
            self.assertTrue((path / "perfetto.json").is_file())
            self.assertEqual(ProfileAnalyzer(path).bottleneck_summary()["dominant"], "UNKNOWN")
            self.assertEqual(json.loads((path / "manifest.json").read_text())["scheduler_policy"], "eclipse")
            with self.assertRaises(FileExistsError):
                run_benchmark(root, ephemeris=ephemeris, run_id="test-axb")

    def test_failed_run_has_no_completed_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_benchmark(root, ephemeris=mock_leo_ephemeris(),
                                   dimension=128, iteration_rate=0.001, run_id="budget-exhausted")
            bundle = json.loads((root / "profiles/budget-exhausted/execution-trace.json").read_text())
            kinds = [event["header"]["event_type"] for event in bundle["events"]]
            self.assertFalse(result["converged"])
            self.assertIn("JOB_FAILED", kinds)
            self.assertNotIn("JOB_COMPLETED", kinds)

    def test_fixed_baseline_and_iteration_budgets(self):
        ephemeris = mock_leo_ephemeris(5760)
        fixed = plan_segments(ephemeris, 0.18, "fixed")
        adaptive = plan_segments(ephemeris, 0.18, "eclipse")
        self.assertEqual(len(fixed), 1)
        self.assertGreater(len(adaptive), 1)
        def budget(segments):
            return sum(tick["iterations"] for segment in segments for tick in segment["ticks"])
        nominal = plan_segments(ephemeris, 0.18, "fixed", eclipse_factor=1)
        self.assertEqual(budget(nominal), 1036)
        self.assertLessEqual(budget(adaptive), budget(nominal))
        self.assertLess(budget(fixed), budget(adaptive))


if __name__ == "__main__":
    unittest.main()
