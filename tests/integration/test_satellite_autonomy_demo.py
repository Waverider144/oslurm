import contextlib
import io
import unittest
from pathlib import Path

from providers.gmat.backend import detect_backend
from oslurm.satellite_demo import run_demo


class SatelliteAutonomyDemoTests(unittest.TestCase):
    @unittest.skipUnless(detect_backend().real, "real GMAT is required; mock fallback is not used")
    def test_satellite_demo_uses_real_gmat_and_finishes_autonomously(self):
        root = Path(__file__).resolve().parents[2]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = run_demo(root)
        text = output.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("GMAT backend: REAL", text)
        self.assertIn("[METRIC] ground_dependent_decisions=0", text)
        self.assertIn("SATELLITE AUTONOMY:\n  PASS", text)


if __name__ == "__main__":
    unittest.main()
