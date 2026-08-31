import subprocess
import sys
import unittest


class ProfileCliIntegrationTests(unittest.TestCase):
    def test_cli_help_entrypoint_imports(self):
        completed = subprocess.run(
            [sys.executable, "-m", "oslurm.cli", "profile", "status"],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("profile inactive", completed.stdout)


if __name__ == "__main__":
    unittest.main()
