import re
from ollamadev_mcp_server.metrics_exporter import collect_metrics_text


def test_collect_metrics_format():
    txt = collect_metrics_text()
    # must include header and one metric line
    assert 'mcp_tool_history_entries' in txt
    # histogram bucket entry format
    assert re.search(r'mcp_tool_duration_ms_bucket\{tool="[A-Za-z0-9_\-]+",le="\+?\w+"\} \d+', txt)
