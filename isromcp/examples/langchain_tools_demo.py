"""
End-to-end check of the adapter path: start every server over stdio with langchain-mcp-adapters,
load all tools as LangChain tools, and call one tool per server.

    uv run python examples/langchain_tools_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: E402

from mcp_config import connections  # noqa: E402

CALLS = {
    "search_isro_documents": {"query": "What was the launch mass of GSAT-7?", "top_k": 2},
    "recent_isro_launches": {"limit": 2},
    "list_isro_missions": {"name_contains": "Chandrayaan", "limit": 5},
    "search_satellites": {"name": "CARTOSAT", "limit": 3},
}


def short(result) -> str:
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return text[:300].replace("\n", " ")


async def main() -> None:
    client = MultiServerMCPClient(connections())
    tools = await client.get_tools()
    print(f"Loaded {len(tools)} LangChain tools from {len(connections())} MCP servers:")
    for t in tools:
        print(f"  - {t.name}: {t.description.splitlines()[0]}")
    by_name = {t.name: t for t in tools}
    print()
    for name, args in CALLS.items():
        try:
            out = await by_name[name].ainvoke(args)
            print(f"[OK]   {name}({args}) -> {short(out)}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
