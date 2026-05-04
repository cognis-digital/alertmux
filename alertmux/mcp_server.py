"""ALERTMUX MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from alertmux.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-alertmux[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-alertmux[mcp]'")
        return 1
    app = FastMCP("alertmux")

    @app.tool()
    def alertmux_scan(target: str) -> str:
        """Alert dedup, correlation, and routing in front of Grafana / PagerDuty. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
