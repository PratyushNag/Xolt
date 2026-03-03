from __future__ import annotations

import asyncio

from xolt import XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime


async def main() -> None:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(skills=["browser-use/browser-use"]),
    )
    try:
        await session.add_agent(
            "reviewer",
            {
                "description": "Review Python code for bugs",
                "mode": "subagent",
                "prompt": "Review code for correctness first, then style.",
            },
        )
        print(await session.list_agents())
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
