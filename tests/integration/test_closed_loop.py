import subprocess
import unittest
from pathlib import Path


class ClosedLoopIntegrationTests(unittest.TestCase):
    def test_demo_runs_and_reports_fail_when_real_backends_missing(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(["./scripts/demo.sh"], cwd=root, capture_output=True, text=True)
        self.assertIn("[CHECKPOINT] job=42 progress=61%", result.stdout)
        self.assertIn("[RESTORE] job=42 progress=61%", result.stdout)
        self.assertIn("[JOB] job=42 COMPLETED", result.stdout)
        self.assertIn("CLOSED LOOP:", result.stdout)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

