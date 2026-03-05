from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from xolt import XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime


class PluginTransport(Protocol):
    async def send_event(self, event: dict[str, Any]) -> None: ...
    async def send_log(self, message: str) -> None: ...


@dataclass
class StdoutTransport:
    async def send_event(self, event: dict[str, Any]) -> None:
        print(f"[event] {event}")

    async def send_log(self, message: str) -> None:
        print(f"[log] {message}")


async def run_plugin_task(prompt: str, transport: PluginTransport) -> None:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(),
    )
    try:
        chat_id = await session.ensure_chat_session(title="IDE Plugin Task")
        task = await session.submit_task(prompt, chat_session_id=chat_id)
        await transport.send_log(f"Task created: {task.id}")

        async for event in session.stream_task(task.id):
            await transport.send_event(
                {
                    "id": event.id,
                    "type": event.type,
                    "task_id": event.task_id,
                    "sequence": event.sequence,
                    "payload": event.payload,
                }
            )
            if event.type == "question_asked":
                blocker = session.get_task_blocker(task.id)
                if blocker is not None:
                    await transport.send_log(f"Blocked by question: {blocker.questions}")
                    await session.resume_blocked_task(task.id, "Proceed with safe defaults.")

        result = await session.wait_task(task.id)
        await transport.send_log(
            f"Task finished with status={result.status}, response={result.response!r}, error={result.error!r}"
        )
    finally:
        await session.close()


async def main() -> None:
    transport = StdoutTransport()
    await run_plugin_task(
        "Inspect this project and suggest one IDE-friendly improvement.",
        transport,
    )


if __name__ == "__main__":
    asyncio.run(main())
