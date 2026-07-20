"""ISAC 入口: `python -m isac` 或 `uv run python -m isac.main`。"""

import asyncio

from isac.main import main

if __name__ == "__main__":
    asyncio.run(main())
