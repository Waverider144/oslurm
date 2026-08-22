import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from providers.gmat.parser import parse_json


class GmatAdapterIntegrationTests(unittest.TestCase):
    def test_mock_adapter_output_parses(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "gmat.json"
            subprocess.run(
                [
                    sys.executable,
                    str(root / "providers/gmat/adapter.py"),
                    "--scenario",
                    str(root / "providers/gmat/scenarios/leo_demo.yaml"),
                    "--output",
                    str(output),
                    "--allow-mock",
                ],
                check=True,
                cwd=root,
            )
            samples, events = parse_json(output)
        self.assertGreaterEqual(len(samples), 4)
        self.assertTrue(any(e.type == "ECLIPSE_ENTRY" for e in events))


if __name__ == "__main__":
    unittest.main()

