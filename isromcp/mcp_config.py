"""
Connection settings for loading the ISRO MCP servers with langchain-mcp-adapters (or any MCP client).

    from langchain_mcp_adapters.client import MultiServerMCPClient
    from mcp_config import connections

    client = MultiServerMCPClient(connections())
    tools = await client.get_tools()          # -> LangChain tools for your LLM / agent

Transports
- The three web-API servers start automatically as stdio subprocesses.
- The knowledge-base (RAG) server runs over streamable HTTP. Start it once, next to Qdrant:
      uv run python servers/knowledge_base_server.py --http        (http://127.0.0.1:8101/mcp)
  Reason: on Windows, its synchronous Qdrant/Azure clients hung when the server was spawned over stdio,
  while the same server works over HTTP and in-process. HTTP also suits a long-lived service that keeps
  its clients and models loaded.
- connections("http") points every server at HTTP (run each with --http).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVERS = ROOT / "servers"
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

# name -> (script, default http port, default transport)
SERVER_FILES = {
    "isro_knowledge_base": ("knowledge_base_server.py", 8101, "http"),
    "launch_library": ("launch_library_server.py", 8102, "stdio"),
    "wikidata": ("wikidata_server.py", 8103, "stdio"),
    "celestrak": ("celestrak_server.py", 8104, "stdio"),
}


def connections(transport: str = "default", only: list[str] | None = None, host: str | None = None) -> dict:
    """transport: 'default' (per-server setting above), 'http' (all HTTP) or 'stdio' (all stdio).
    host: where the HTTP servers run; default MCP_HOST env var, else 127.0.0.1 (docker compose sets 'mcp')."""
    host = host or os.environ.get("MCP_HOST", "127.0.0.1")
    out = {}
    for name, (script, port, default) in SERVER_FILES.items():
        if only and name not in only:
            continue
        mode = default if transport == "default" else transport
        if mode == "stdio":
            out[name] = {"transport": "stdio", "command": str(PYTHON), "args": [str(SERVERS / script)],
                         "cwd": str(SERVERS)}
        else:
            out[name] = {"transport": "streamable_http", "url": f"http://{host}:{port}/mcp"}
    return out
