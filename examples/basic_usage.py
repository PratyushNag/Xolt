from __future__ import annotations

import asyncio

from xolt import XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime


async def main() -> None:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(),
    )
    try:
        print(await session.preview_url())
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
