import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from oslurm.transport import LoopbackTCPTransport
from oslurm.network.checkpoint import sha256


class TransportTests(unittest.TestCase):
    def setUp(self):
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
        except PermissionError:
            self.skipTest("sandbox denies TCP sockets; run make test-tcp with local network permission")

    def test_real_tcp_large_payload_and_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.write_bytes(bytes(range(256)) * 10000)
            receipt = LoopbackTCPTransport().copy(source, target)
            self.assertEqual(receipt["bytes"], source.stat().st_size)
            self.assertEqual(sha256(source), sha256(target))
            self.assertEqual(receipt["sha256"], sha256(target))
        self.assertFalse(any(t.name == "oslurm-tcp-receiver" for t in threading.enumerate()))

    def test_limit_failure_and_connect_failure_terminate(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.write_bytes(b"payload")
            with self.assertRaises(ValueError):
                LoopbackTCPTransport(max_bytes=1).copy(source, target)
            with patch("oslurm.transport.socket.create_connection", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    LoopbackTCPTransport(timeout_s=.02).copy(source, target)
        self.assertFalse(any(t.name == "oslurm-tcp-receiver" for t in threading.enumerate()))

    def test_real_joint_mission_cpp_tcp(self):
        from oslurm.joint_execution import run_joint_axb
        from oslurm.network.runtime import MultiConstellationRuntime
        runtime = MultiConstellationRuntime(Path.cwd())
        runtime.load_constellation("compute", "configs/compute-ai.yaml")
        runtime.load_constellation("comm", "configs/relay-public.yaml")
        runtime.connect("compute-ai", "relay-public")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_joint_axb(Path(tmp), dimension=128, runtime=runtime, contact_mode="fixtures",
                                   transport="tcp", solver="cpp")
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["worker"]["solver_backend"], "cpp")
        self.assertGreater(result["physical_transfer_wall_s"], 0)


if __name__ == "__main__":
    unittest.main()
