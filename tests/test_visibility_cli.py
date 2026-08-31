import unittest
from pathlib import Path

from oslurm.cli import OslurmCli


class VisibilityCliTests(unittest.TestCase):
    def test_visibility_check_and_explain_link(self):
        cli = OslurmCli(Path.cwd())
        blocked = cli.execute("visibility check compute/SAT-A compute/SAT-C")
        self.assertIn("FINAL:\nNOT VISIBLE", blocked)
        self.assertIn("EARTH_OCCULTATION", blocked)
        explanation = cli.execute("topology explain-link compute/SAT-A compute/SAT-C")
        self.assertIn("Earth occultation: FAIL", explanation)

    def test_fov_rejected_link(self):
        cli = OslurmCli(Path.cwd())
        rejected = cli.execute("visibility check compute/SAT-A compute/SAT-D")
        self.assertIn("FINAL:\nNOT VISIBLE", rejected)
        self.assertIn("DESTINATION_FOV_VIOLATION", rejected)


if __name__ == "__main__":
    unittest.main()
