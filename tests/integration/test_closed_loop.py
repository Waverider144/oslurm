import subprocess
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch


class ClosedLoopIntegrationTests(unittest.TestCase):
    def test_demo_reports_actual_backend_outcome(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(["./scripts/demo.sh"], cwd=root, capture_output=True, text=True)
        self.assertIn("[CHECKPOINT] job=42 progress=61%", result.stdout)
        self.assertIn("[RESTORE] job=42 progress=61%", result.stdout)
        self.assertIn("[JOB] job=42 COMPLETED", result.stdout)
        self.assertIn("CLOSED LOOP:", result.stdout)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        if result.returncode == 0:
            self.assertIn("  PASS", result.stdout)
            self.assertIn("GMAT backend: REAL", result.stdout)
            self.assertIn("Slurm backend: REAL", result.stdout)
        else:
            self.assertIn("  FAIL", result.stdout)

    def test_missing_real_slurm_never_reports_closed_loop_pass(self):
        from oslurm.demo import run_demo
        output = StringIO()
        with patch("oslurm.demo.SlurmBridge") as bridge, redirect_stdout(output):
            bridge.return_value.status.backend = "MOCK"
            bridge.return_value.status.version = "test"
            bridge.return_value.available_nodes.return_value = ["sat001", "sat002", "sat003", "sat004"]
            bridge.return_value.submit.return_value = ("test-mock", "RUNNING")
            bridge.return_value.migrate.return_value = "REQUEUED_MOCK"
            result = run_demo(Path(__file__).resolve().parents[2])
        self.assertNotEqual(result, 0)
        self.assertIn("  FAIL", output.getvalue())


if __name__ == "__main__":
    unittest.main()

