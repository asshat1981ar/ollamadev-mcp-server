"""Background HTTP metrics server exposing /metrics plaintext.

This lightweight server runs in a daemon thread on a configurable port and
serves Prometheus plaintext gathered from the local metrics_exporter.collect_metrics_text().
It's intended as an MVP until a full Prometheus client or exporter is added.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import os
from typing import Tuple

from ollamadev_mcp_server.metrics_exporter import collect_metrics_text


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        text = collect_metrics_text().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(text)))
        self.end_headers()
        self.wfile.write(text)

    def log_message(self, format, *args):
        # suppress default logging
        return


def start_metrics_server(host: str = "127.0.0.1", port: int = 8001) -> Tuple[threading.Thread, HTTPServer]:
    """Start the metrics server on host:port in a daemon thread.

    Returns: (thread, server) so callers may stop the server in tests.
    """
    server = HTTPServer((host, port), _MetricsHandler)

    def _run():
        try:
            server.serve_forever()
        finally:
            server.server_close()

    t = threading.Thread(target=_run, name="MetricsServerThread", daemon=True)
    t.start()
    return t, server


def start_from_env():
    host = os.environ.get("METRICS_HOST", "127.0.0.1")
    port = int(os.environ.get("METRICS_PORT", "8001"))
    return start_metrics_server(host, port)
