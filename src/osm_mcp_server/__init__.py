from . import server
import argparse


def main():
    """Main entry point for the package."""
    parser = argparse.ArgumentParser(description="OpenStreetMap MCP Server")
    parser.add_argument(
        "--mode",
        type=str,
        default="streamable-http",
        choices=["streamable-http", "stdio", "sse"],
        help="Server transport mode (default: streamable-http)",
    )
    args = parser.parse_args()
    if args.mode == "streamable-http":
        print("Starting MCP server in streamable-http mode...")
    elif args.mode == "stdio":
        print("Starting MCP server in stdio mode...")
    elif args.mode == "sse":
        print("Starting MCP server in SSE mode...")

    server.mcp.run(
        transport=args.mode,
    )


# Optionally expose other important items at package level
__all__ = ["main", "server"]
