"""ALERTMUX MCP server — exposes the alertmux pipeline as an MCP tool."""
from __future__ import annotations

import json
import sys


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-alertmux[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print(
            "Install the MCP extra: pip install 'cognis-alertmux[mcp]'",
            file=sys.stderr,
        )
        return 1

    from alertmux.core import Engine, load_alerts

    app = FastMCP("alertmux")

    @app.tool()
    def alertmux_process(alerts_json: str) -> str:
        """Dedup, correlate, and route raw alerts.

        Pass a JSON string containing either a list of alert objects or an
        Alertmanager webhook payload (``{"alerts": [...]}}``).
        Returns a JSON string with ``incidents`` and ``summary`` keys.
        """
        try:
            raw = json.loads(alerts_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"invalid JSON: {exc}"})
        try:
            alerts = load_alerts(raw)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        engine = Engine()
        incidents = engine.process(alerts)
        return json.dumps(
            {
                "summary": {
                    "events": len(alerts),
                    "incidents": len(incidents),
                    "paging": sum(1 for i in incidents if i.page),
                },
                "incidents": [i.to_dict() for i in incidents],
            },
            default=str,
        )

    app.run()
    return 0
