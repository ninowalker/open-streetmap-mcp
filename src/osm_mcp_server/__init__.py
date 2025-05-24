from . import server


def main():
    """Main entry point for the package."""
    print("Starting MCP server in streamable-http mode...")
    server.mcp.run(
        transport="streamable-http",
        mount_path="/mcp",
    )


# Optionally expose other important items at package level
__all__ = ["main", "server"]
