"""HTTP server that never performs reverse DNS during loopback binding."""
from __future__ import annotations

import socketserver
from http.server import ThreadingHTTPServer


class LoopbackHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with deterministic 127.0.0.1 startup.

    HTTPServer.server_bind() calls socket.getfqdn(host), which can block for
    many seconds on isolated or sandboxed desktops. Relay only binds to
    loopback and never needs a hostname, so use the socket address directly.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

