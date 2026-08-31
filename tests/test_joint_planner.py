import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from oslurm.cli import OslurmCli
from oslurm.network.runtime import MultiConstellationRuntime


class JointPlannerTests(unittest.TestCase):
    def test_network_changes_compute_placement(self):
        runtime = MultiConstellationRuntime(Path.cwd())
        runtime.load_constellation("compute", "configs/compute-ai.yaml")
        runtime.load_constellation("comm", "configs/relay-public.yaml")
        runtime.connect("compute-ai", "relay-public")
        out = runtime.submit_job("workloads/inference.yaml", None)
        self.assertIn("selected=compute:SAT003", out)

    def test_relay_b_is_operational_in_default_network(self):
        runtime = MultiConstellationRuntime(Path.cwd())
        runtime.load_constellation("compute", "configs/compute-ai.yaml")
        runtime.load_constellation("comm", "configs/relay-public.yaml")
        runtime.connect("compute-ai", "relay-public")
        contact_ids = {contact.contact_id for contact in runtime.network.contacts}
        self.assertIn("GROUND-RELAY-B", contact_ids)
        self.assertIn("RELAY-B-SAT002", contact_ids)
        self.assertIn("SAT002-RELAY-B", contact_ids)
        self.assertIn("RELAY-B-GROUND", contact_ids)
        self.assertIn("comm:RELAY-B", runtime.network.buffers)

    def test_cli_acceptance_session(self):
        with TemporaryDirectory() as tmp:
            cli = OslurmCli(Path.cwd())
            cli.root = Path(tmp)
            cli.network.root = Path.cwd()
            self.assertIn("loaded compute constellation", cli.execute("load constellation compute configs/compute-ai.yaml"))
            self.assertIn("loaded comm constellation", cli.execute("load constellation comm configs/relay-public.yaml"))
            self.assertIn("connected", cli.execute("connect constellations compute-ai relay-public"))
            self.assertIn("profile on", cli.execute("profile on --mode full --run-id joint-test"))
            self.assertIn("selected=compute:SAT003", cli.execute("submit job workloads/inference.yaml"))
            self.assertIn("advanced network runtime", cli.execute("run 2h"))
            self.assertIn("JOB001", cli.execute("profile timeline JOB001"))
            self.assertIn("network_changed_compute_placements: 1", cli.execute("profile network"))
            self.assertIn("profile off", cli.execute("profile off"))


if __name__ == "__main__":
    unittest.main()
