import unittest

from oslurm.network import BufferState, NetworkDomain, NetworkNodeId


class NetworkModelTests(unittest.TestCase):
    def test_node_id_parsing_and_buffer_accounting(self):
        self.assertEqual(NetworkNodeId.parse("comm:RELAY-A").domain, NetworkDomain.COMM)
        self.assertEqual(str(NetworkNodeId.parse("SAT001")), "compute:SAT001")
        buffer = BufferState(capacity_bytes=100, used_bytes=25, reserved_bytes=50)
        self.assertEqual(buffer.available_bytes, 25)


if __name__ == "__main__":
    unittest.main()
