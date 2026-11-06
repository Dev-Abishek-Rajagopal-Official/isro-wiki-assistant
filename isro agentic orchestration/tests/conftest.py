import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.platform == "win32":  # psycopg async needs the selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
