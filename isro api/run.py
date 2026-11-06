"""
Start the API server.

    uv run python run.py [--host 127.0.0.1] [--port 8000] [--reload]

On Windows the selector event loop is set first (psycopg async cannot run on the Proactor loop) and
uvicorn is told not to replace it (loop="none").
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn
from orchestrator.service import use_selector_event_loop


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    use_selector_event_loop()
    config = uvicorn.Config("app.main:app", host=args.host, port=args.port, loop="none", log_level="info",
                            ws_max_size=40 * 1024 * 1024)
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
