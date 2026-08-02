"""Small demo client for the OllamaDev MCP server."""
import asyncio
import json
from mcp.client import Client

SERVER_URL = "http://localhost:5000/mcp"


def fmt(result):
    if hasattr(result, "content"):
        for item in result.content:
            if hasattr(item, "text"):
                return item.text
    return str(result)


async def main():
    async with Client(server=SERVER_URL, mode="auto") as client:
        print("=== server info ===")
        print(client.server_info)
        print("=== protocol version ===")
        print(client.protocol_version)

        print("\n=== tools/list (first 10) ===")
        tools = await client.list_tools()
        for t in tools.tools[:10]:
            print(f"- {t.name}: {t.description[:80]}...")
        print(f"...total tools: {len(tools.tools)}")

        print("\n=== ping ===")
        print(fmt(await client.call_tool("ping")))

        print("\n=== describe_tools (verification) ===")
        print(fmt(await client.call_tool("describe_tools", {"category": "verification"}))[:600])

        print("\n=== list_workspace_files (root='app/src/main/java/com/example/ui') ===")
        files = fmt(await client.call_tool("list_workspace_files", {"root": "app/src/main/java/com/example/ui"}))
        for line in files.splitlines()[:15]:
            print(line)
        if len(files.splitlines()) > 15:
            print("...")

        print("\n=== read_workspace_file (MainActivity.kt, first 30 lines) ===")
        text = fmt(await client.call_tool("read_workspace_file", {"path": "app/src/main/java/com/example/MainActivity.kt"}))
        for line in text.splitlines()[:30]:
            print(line)

        print("\n=== search_workspace ('SwarmViewModel') ===")
        print(fmt(await client.call_tool("search_workspace", {"pattern": "class SwarmViewModel", "context_lines": 0})))

        print("\n=== get_file_outline (SwarmViewModel.kt) ===")
        outline = fmt(await client.call_tool("get_file_outline", {"path": "app/src/main/java/com/example/viewmodel/SwarmViewModel.kt"}))
        for line in outline.splitlines()[:20]:
            print(line)

        print("\n=== suggest_next_action ===")
        try:
            suggestion = fmt(await client.call_tool("suggest_next_action", {
                "goal": "Refactor the OllamaDev Android app to extract reusable UI components from duplicated cards across screens.",
                "phase": "DESIGN",
                "context": "Screens are flat under ui/; each screen defines its own local cards. No shared component package exists yet.",
                "model": "deepseek-v4-flash",
                "provider": "ollama",
            }))
            print(suggestion)
        except Exception as exc:
            print(f"suggest_next_action failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
