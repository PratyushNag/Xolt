from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from xolt import TaskEvent, XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
except ImportError as exc:  # pragma: no cover - optional example dependency
    raise SystemExit(
        "This example requires FastAPI and Uvicorn:\n"
        "  uv add fastapi uvicorn\n"
        "  uv run uvicorn examples.embedding_web_backend:app --reload"
    ) from exc


app = FastAPI(title="Xolt Embedding Backend")


async def _task_stream(prompt: str) -> AsyncIterator[str]:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(),
    )
    try:
        chat_id = await session.ensure_chat_session(title="Web Backend Task")
        task = await session.submit_task(prompt, chat_session_id=chat_id)

        async for event in session.stream_task(task.id):
            yield f"data: {json.dumps(_event_to_wire(event))}\n\n"

        result = await session.wait_task(task.id)
        yield f"data: {json.dumps({'type': 'task_result', 'payload': _result_to_wire(result)})}\n\n"
    finally:
        await session.close()


def _event_to_wire(event: TaskEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type,
        "task_id": event.task_id,
        "chat_session_id": event.chat_session_id,
        "sequence": event.sequence,
        "payload": event.payload,
        "ts": event.ts.isoformat(),
    }


def _result_to_wire(result: Any) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "chat_session_id": result.chat_session_id,
        "status": result.status,
        "response": result.response,
        "error": result.error,
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks/stream")
async def stream_task(payload: dict[str, Any]) -> StreamingResponse:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="`prompt` must be non-empty")
    return StreamingResponse(_task_stream(prompt), media_type="text/event-stream")
