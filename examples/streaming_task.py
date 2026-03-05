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
        chat_id = await session.ensure_chat_session(title="Streaming Example")
        task = await session.submit_task(
            "Inspect the current project and propose one small improvement.",
            chat_session_id=chat_id,
            metadata={"example": "streaming_task"},
        )

        print(f"Task: {task.id}")
        print(f"Chat: {task.chat_session_id}")
        async for event in session.stream_task(task.id):
            if event.type == "message_delta":
                print(event.payload.get("delta", ""), end="")
            elif event.type == "file_changed":
                print(f"\n[file] {event.payload}")
            elif event.type == "status":
                print(f"\n[status] {event.payload}")

        result = await session.wait_task(task.id, timeout=900)
        print(f"\nResult status: {result.status}")
        if result.response:
            print(f"Result response: {result.response}")
        if result.error:
            print(f"Result error: {result.error}")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
