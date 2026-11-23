"""Call any Vizier tool from the shell, without an MCP client.

    .venv/bin/python -m chancellor.cli get_turn_review
    .venv/bin/python -m chancellor.cli get_amenity_options '{"city": "Nagoya"}'
    .venv/bin/python -m chancellor.cli --fixture tests/fixtures/midgame.json get_rivals
    .venv/bin/python -m chancellor.cli --list

Runs the real server in-process over an in-memory MCP session, so output is
identical to what an MCP client gets. Used by the project skills as a
fallback when the chancellor MCP server isn't loaded in the session.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


async def _call(tool: str | None, args: dict) -> int:
    from mcp.shared.memory import create_connected_server_and_client_session

    from chancellor.server import mcp

    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        if tool is None:
            for t in (await client.list_tools()).tools:
                print(f"{t.name}: {(t.description or '').strip().splitlines()[0]}")
            return 0
        res = await client.call_tool(tool, args)
        print("".join(getattr(c, "text", "") for c in res.content))
        return 1 if res.isError else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="chancellor.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tool", nargs="?", help="tool name, e.g. get_turn_review")
    p.add_argument("args", nargs="?", default="{}", help="JSON object of arguments")
    p.add_argument("--fixture", help="run against a recorded snapshot instead of the live game")
    p.add_argument("--list", action="store_true", help="list tools")
    a = p.parse_args()
    if a.fixture:
        os.environ["CHANCELLOR_FIXTURE"] = a.fixture
    if not a.list and not a.tool:
        p.error("give a tool name, or --list")
    try:
        args = json.loads(a.args)
    except json.JSONDecodeError as e:
        p.error(f"args must be a JSON object: {e}")
    sys.exit(asyncio.run(_call(None if a.list else a.tool, args)))


if __name__ == "__main__":
    main()
