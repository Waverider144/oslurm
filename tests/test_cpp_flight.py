import ctypes as C
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from oslurm.axb import ConjugateGradient, run_segment
from oslurm.cpp import Candidate, Request, advance_cg, library
from oslurm.satellite.embedded import EmbeddedSatelliteScheduler
from oslurm.satellite.policies import DeterministicSatelliteScheduler
from oslurm.satellite.context import LocalSchedulingContext
from oslurm.satellite.neighbor_table import NeighborSchedulingTable
from oslurm.satellite.advertisement import generate_advertisement
from tests import test_satellite_autonomy as reference


class CppPolicyTests(reference.SatelliteAutonomyTests):
    def setUp(self):
        library()
        replacement = patch.object(reference, "DeterministicSatelliteScheduler", EmbeddedSatelliteScheduler)
        replacement.start()
        self.addCleanup(replacement.stop)


class CppFlightTests(unittest.TestCase):
    def test_cpp_solver_matches_python_and_resumes(self):
        for dimension in (2, 48, 256, 4096):
            python, cpp = ConjugateGradient(dimension), ConjugateGradient(dimension)
            python.advance(20000)
            advance_cg(cpp, 17)
            with tempfile.TemporaryDirectory() as tmp:
                checkpoint = Path(tmp) / "state.npz"
                cpp.save(checkpoint)
                cpp = ConjugateGradient.load(checkpoint)
                advance_cg(cpp, 20000)
            self.assertTrue(cpp.converged)
            np.testing.assert_allclose(cpp.x, python.x, atol=1e-8)
            self.assertLessEqual(cpp.residual, cpp.tolerance)

    def test_cpp_solver_rejects_unsafe_state(self):
        cpp = ConjugateGradient(48)
        with self.assertRaises(ValueError):
            advance_cg(cpp, -1)
        cpp.p[0] = np.nan
        with self.assertRaises(ArithmeticError):
            advance_cg(cpp, 1)

    def test_randomized_reference_decisions(self):
        rng = random.Random(42)
        for _ in range(500):
            table = NeighborSchedulingTable()
            local = reference.node("SAT01", links=("SAT02", "SAT03"))
            windows = [reference.window(f"SAT{i:02d}", soc=rng.randrange(20, 95) / 100,
                peak=rng.randrange(20, 85), duration_s=rng.randrange(20, 600)) for i in (1, 2, 3)]
            for i in (2, 3):
                table.update(generate_advertisement(reference.node(f"SAT{i:02d}"), windows[i-1], 0, 1))
            context = LocalSchedulingContext(0, local, [windows[0]], table)
            expected = DeterministicSatelliteScheduler("SAT01").on_job_arrival(reference.job(), reference.intent(), context)
            actual = EmbeddedSatelliteScheduler("SAT01").on_job_arrival(reference.job(), reference.intent(), context)
            self.assertEqual((actual.decision_type, actual.peer), (expected.decision_type, expected.peer))

    def test_c_api_bounds_stale_and_overflow(self):
        request = Request(2**64-100, 2**64-1, 2**64-1, 1000, 1, 32, 300000, 70000, 2, 0, 7)
        candidates = (Candidate * 1)(Candidate(10000, 0, 1, 64, 900000, 30000, 100, 0, 0, 1))
        result = library().oslurm_decide(C.byref(request), candidates, 1)
        self.assertEqual(result.action, 2)
        self.assertTrue(result.rejected[0] & 32)
        self.assertTrue(result.rejected[0] & 64)
        self.assertEqual(library().oslurm_decide(C.byref(request), candidates, 17).action, 4)

    def test_oversized_neighbor_table_fails_closed(self):
        table = NeighborSchedulingTable()
        links = tuple(f"SAT{i:02d}" for i in range(2, 19))
        for peer in links:
            table.update(generate_advertisement(reference.node(peer), reference.window(peer), 0, 1))
        context = LocalSchedulingContext(0, reference.node("SAT01", links), [reference.window("SAT01")], table)
        result = EmbeddedSatelliteScheduler("SAT01").on_job_arrival(reference.job(), reference.intent(), context)
        self.assertEqual(result.decision_type.value, "REJECT")

    def test_real_orbit_agent_uses_cpp_core(self):
        from oslurm.orbit_benchmark import run_benchmark
        from tests.test_checkpoint_network import ephemeris
        with tempfile.TemporaryDirectory() as tmp:
            result = run_benchmark(Path(tmp), ephemeris=ephemeris(), dimension=128,
                                   decision_core="cpp", iteration_rate=2)
        self.assertEqual(result["autonomy"]["decision_core"], "cpp")
        self.assertGreater(result["autonomy"]["autonomous_decisions"], 0)


if __name__ == "__main__":
    unittest.main()
