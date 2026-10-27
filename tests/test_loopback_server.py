from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import loopback_server


class LoopbackServerTests(unittest.TestCase):
    def test_binding_does_not_perform_reverse_dns(self):
        with patch.object(loopback_server.socketserver.TCPServer, "server_bind") as bind, \
             patch("socket.getfqdn", side_effect=AssertionError("reverse DNS must not run")):
            class FakeServer:
                server_address = ("127.0.0.1", 18765)
                server_name = ""
                server_port = 0

            fake = FakeServer()
            loopback_server.LoopbackHTTPServer.server_bind(fake)
        bind.assert_called_once()
        self.assertEqual(fake.server_name, "127.0.0.1")
        self.assertEqual(fake.server_port, 18765)


if __name__ == "__main__":
    unittest.main()
