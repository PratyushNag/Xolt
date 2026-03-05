from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from xolt import XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime


@dataclass
class Job:
    id: str
    prompt: str
    metadata: dict[str, str] = field(default_factory=dict)


async def run_job(job: Job) -> dict[str, Any]:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(),
    )
    try:
        chat_id = await session.ensure_chat_session(title=f"Queue Job {job.id}")
        task = await session.submit_task(
            job.prompt,
            chat_session_id=chat_id,
            metadata=job.metadata,
        )
        async for event in session.stream_task(task.id):
            if event.type == "status":
                print(f"[{job.id}] status: {event.payload}")
            if event.type == "file_changed":
                print(f"[{job.id}] file: {event.payload}")
        result = await session.wait_task(task.id)
        return {
            "job_id": job.id,
            "task_id": result.task_id,
            "status": result.status,
            "response": result.response,
            "error": result.error,
        }
    finally:
        await session.close()


async def worker(queue: asyncio.Queue[Job]) -> None:
    while True:
        job = await queue.get()
        try:
            output = await run_job(job)
            print(f"Completed {job.id}: {output['status']}")
        except Exception as exc:
            print(f"Job {job.id} failed: {exc}")
        finally:
            queue.task_done()


async def main() -> None:
    queue: asyncio.Queue[Job] = asyncio.Queue()
    await queue.put(Job(id="job-1", prompt="Summarize the repository architecture."))
    await queue.put(Job(id="job-2", prompt="Suggest one low-risk refactor."))

    worker_task = asyncio.create_task(worker(queue))
    await queue.join()
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task


if __name__ == "__main__":
    asyncio.run(main())
