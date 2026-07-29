"""
OllamaDev companion MCP server — MCP Python SDK v2 beta.

Exposes a comprehensive toolbox of ~22 tools over HTTP Streamable transport.
Connect from OllamaDev: Add Server → URL: http://<host>:5000/mcp
"""

from mcp.server import MCPServer

from ollamadev_mcp_server.tools import (
    build, code, dependencies, filesystem, git_tools, memory, meta, observability, patch, sandbox, sprint,
)


def main() -> None:
    mcp = MCPServer("OllamaDev Toolbox")

    filesystem.register(mcp)
    code.register(mcp)
    build.register(mcp)
    sprint.register(mcp)
    memory.register(mcp)
    meta.register(mcp)
    patch.register(mcp)
    git_tools.register(mcp)
    dependencies.register(mcp)
    observability.register(mcp)
    sandbox.register(mcp)

    mcp.run(transport="streamable-http", host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
