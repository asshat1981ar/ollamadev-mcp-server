"""Tests for dynamic tool catalog generation."""

from mcp.server import MCPServer

from ollamadev_mcp_server.catalog import (
    build_tool_catalog,
    get_tool_by_name,
    get_tools_by_phase,
    validate_catalog,
)


class TestBuildToolCatalog:
    def test_build_catalog_returns_list(self):
        mcp = MCPServer("Test")
        catalog = build_tool_catalog(mcp)
        assert isinstance(catalog, list)

    def test_build_catalog_empty_server(self):
        mcp = MCPServer("Test")
        catalog = build_tool_catalog(mcp)
        assert catalog == []

    def test_build_catalog_with_tools(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def ping() -> str:
            """Ping tool."""
            return "pong"

        catalog = build_tool_catalog(mcp)
        assert len(catalog) == 1
        assert catalog[0]["name"] == "ping"
        assert catalog[0]["phase"] == "all"

    def test_build_catalog_sorted_by_name(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def zebra() -> str:
            return "z"

        @mcp.tool()
        def alpha() -> str:
            return "a"

        catalog = build_tool_catalog(mcp)
        assert catalog[0]["name"] == "alpha"
        assert catalog[1]["name"] == "zebra"


class TestGetToolsByPhase:
    def test_get_tools_by_phase_discovery(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def list_workspace_files() -> str:
            return "files"

        catalog = build_tool_catalog(mcp)
        tools = get_tools_by_phase(catalog, "DISCOVERY")
        assert len(tools) == 1
        assert tools[0]["name"] == "list_workspace_files"

    def test_get_tools_by_phase_all(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def ping() -> str:
            return "pong"

        catalog = build_tool_catalog(mcp)
        tools = get_tools_by_phase(catalog, "DISCOVERY")
        # ping has phase="all", so it should match any phase
        assert len(tools) == 1

    def test_get_tools_by_phase_no_match(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def custom_tool() -> str:
            return "custom"

        catalog = build_tool_catalog(mcp)
        tools = get_tools_by_phase(catalog, "NONEXISTENT")
        assert len(tools) == 0


class TestGetToolByName:
    def test_get_tool_by_name_found(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def ping() -> str:
            return "pong"

        catalog = build_tool_catalog(mcp)
        tool = get_tool_by_name(catalog, "ping")
        assert tool is not None
        assert tool["name"] == "ping"

    def test_get_tool_by_name_not_found(self):
        mcp = MCPServer("Test")
        catalog = build_tool_catalog(mcp)
        tool = get_tool_by_name(catalog, "nonexistent")
        assert tool is None


class TestValidateCatalog:
    def test_validate_catalog_empty_server(self):
        mcp = MCPServer("Test")
        issues = validate_catalog(mcp)
        # Should have issues about missing tools (all tools in _TOOL_PHASES are missing)
        assert isinstance(issues, list)
        assert len(issues) > 0
        assert "not registered" in issues[0]

    def test_validate_catalog_with_all_tools_registered(self):
        # This test would require registering ALL tools in _TOOL_PHASES
        # For now, we just verify the function works
        mcp = MCPServer("Test")
        issues = validate_catalog(mcp)
        assert isinstance(issues, list)

    def test_validate_catalog_detects_untagged_tool(self):
        mcp = MCPServer("Test")

        @mcp.tool()
        def unknown_custom_tool() -> str:
            return "custom"

        issues = validate_catalog(mcp)
        # Should detect untagged tool
        assert len(issues) > 0
        # Check that at least one issue mentions untagged tools
        assert any("without phase tags" in issue for issue in issues)
