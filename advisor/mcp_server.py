"""MCP server exposing the advisor's read-only tools (plan §7.3).

The tool implementations live in :mod:`advisor.tools` — framework-free.
This module is only an adapter: it registers each registry entry with
the official ``mcp`` Python SDK (FastMCP) so external MCP clients
(Claude, IDEs, the MCP inspector) can list and call the same tools the
LangGraph advisor uses. Scope is identical by construction: only
``read-only`` registry entries are exposed, and tool args are validated
by the same Pydantic input models via :func:`advisor.tools.run_tool`.

Transports:
- stdio (default): ``python -m advisor.mcp_server``
- streamable HTTP: ``python -m advisor.mcp_server --http --port 8765``
  (bind inside the cluster / localhost only — tools need no auth secrets,
  but the server is not a public surface).

Django must be set up before tools touch the ORM, hence ``django.setup()``
in :func:`build_server` when run standalone.
"""

import argparse
import json


def build_server():
    """Create the FastMCP server with every read-only tool registered."""
    import django

    django.setup()

    from mcp.server.fastmcp import FastMCP

    from advisor.tools import TOOL_REGISTRY, run_tool

    server = FastMCP("creditmate-advisor")

    for name, spec in TOOL_REGISTRY.items():
        if spec.scope != "read-only":
            continue

        def _make(tool_name, description):
            def _tool(args: dict | None = None) -> str:
                output, _latency = run_tool(tool_name, args or {})
                return json.dumps(output.model_dump(mode="json"), default=str)

            _tool.__name__ = tool_name
            _tool.__doc__ = description
            return _tool

        server.tool(name=name)(_make(name, spec.description))
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="CreditMate advisor MCP server")
    parser.add_argument("--http", action="store_true", help="streamable HTTP transport")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = build_server()
    if args.http:
        server.settings.port = args.port
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
