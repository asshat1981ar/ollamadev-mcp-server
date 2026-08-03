import urllib.request
import time

from ollamadev_mcp_server.metrics_server import start_metrics_server


def test_metrics_endpoint_returns_prometheus_text():
    # Start server on ephemeral port
    thread, server = start_metrics_server(host="127.0.0.1", port=0)
    try:
        host, port = server.server_address
        url = f"http://{host}:{port}/metrics"
        # give server a moment to start
        time.sleep(0.05)
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read().decode("utf-8")
        assert "mcp_tool_history_entries" in body
    finally:
        try:
            server.shutdown()
            thread.join(timeout=1)
        except Exception:
            pass
