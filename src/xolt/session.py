# SPDX-License-Identifier: Apache-2.0

"""Public Xolt session object."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from xolt.backends.base import BackendHandle, ExecutionBackend
from xolt.exceptions import SessionError
from xolt.runtimes.base import EventCallback, ManagedRuntime, RuntimeHandle
from xolt.tasking import (
    TaskArtifact,
    TaskDiffEntry,
    TaskEvent,
    TaskFileChange,
    TaskHandle,
    TaskResult,
    TaskStatus,
)


@dataclass
class _TaskState:
    handle: TaskHandle
    status: TaskStatus = "running"
    last_error: str | None = None
    final_response: str | None = None
    next_sequence: int = 0
    terminal_event_emitted: bool = False
    last_event_at: datetime | None = None
    file_changes: list[TaskFileChange] = field(default_factory=list)
    events: list[TaskEvent] = field(default_factory=list)
    _queue: asyncio.Queue[TaskEvent] = field(default_factory=asyncio.Queue)


class XoltSession:
    """Public orchestration object for a managed execution session."""

    def __init__(
        self,
        *,
        backend: BackendHandle,
        runtime: RuntimeHandle,
        backend_adapter: ExecutionBackend,
        runtime_adapter: ManagedRuntime,
    ) -> None:
        self.backend = backend
        self.runtime = runtime
        self._backend_adapter = backend_adapter
        self._runtime_adapter = runtime_adapter
        self._active_chat_session_id: str | None = None
        self._tasks: dict[str, _TaskState] = {}

    @classmethod
    async def create(
        cls,
        *,
        backend: ExecutionBackend,
        runtime: ManagedRuntime,
    ) -> XoltSession:
        backend_handle = await backend.create()
        runtime_handle = await runtime.start(backend_handle)
        return cls(
            backend=backend_handle,
            runtime=runtime_handle,
            backend_adapter=backend,
            runtime_adapter=runtime,
        )

    @classmethod
    async def attach(
        cls,
        sandbox_id: str,
        *,
        backend: ExecutionBackend,
        runtime: ManagedRuntime,
        session_id: str = "",
        cmd_id: str = "",
    ) -> XoltSession:
        backend_handle = await backend.attach(sandbox_id)
        runtime_handle = await runtime.attach(
            backend_handle,
            session_id=session_id,
            cmd_id=cmd_id,
        )
        return cls(
            backend=backend_handle,
            runtime=runtime_handle,
            backend_adapter=backend,
            runtime_adapter=runtime,
        )

    @property
    def session_id(self) -> str:
        return self.runtime.session_id

    @property
    def cmd_id(self) -> str:
        return self.runtime.cmd_id

    @property
    def installed_skills(self) -> list[str]:
        return list(self.runtime.installed_skills)

    @property
    def deployed_agents(self) -> list[str]:
        return list(self.runtime.deployed_agents)

    async def preview_url(self) -> str:
        return await self.runtime.preview_url()

    async def add_skill(self, skill_source: str, *, reload: bool = True) -> bool:
        return await self.runtime.add_skill(skill_source, reload=reload)

    async def add_skills(
        self,
        skills: list[str],
        *,
        reload: bool = True,
    ) -> tuple[list[str], list[str]]:
        return await self.runtime.add_skills(skills, reload=reload)

    async def list_skills(self) -> list[str]:
        return await self.runtime.list_skills()

    async def reload_runtime(self) -> None:
        await self.runtime.reload_runtime()

    async def add_agent(self, name: str, config: Any, *, reload: bool = True) -> None:
        await self.runtime.add_agent(name, config, reload=reload)

    async def remove_agent(self, name: str, *, reload: bool = True) -> None:
        await self.runtime.remove_agent(name, reload=reload)

    async def list_agents(self) -> list[str]:
        return await self.runtime.list_agents()

    async def create_chat_session(self, *, title: str | None = None) -> dict[str, Any]:
        created = await self.runtime.create_chat_session(title=title)
        chat_session_id = str(created.get("id", "")).strip()
        if chat_session_id:
            self._active_chat_session_id = chat_session_id
        return created

    async def list_chat_sessions(self) -> list[dict[str, Any]]:
        return await self.runtime.list_chat_sessions()

    @property
    def active_chat_session_id(self) -> str | None:
        return self._active_chat_session_id

    async def ensure_chat_session(self, *, title: str | None = None) -> str:
        if self._active_chat_session_id is not None:
            return self._active_chat_session_id
        created = await self.create_chat_session(title=title)
        chat_session_id = str(created.get("id", "")).strip()
        if not chat_session_id:
            raise SessionError("Runtime returned a chat session without an id.")
        self._active_chat_session_id = chat_session_id
        return chat_session_id

    def set_active_chat_session(self, chat_session_id: str) -> None:
        resolved = chat_session_id.strip()
        if not resolved:
            raise SessionError("chat_session_id must be non-empty")
        self._active_chat_session_id = resolved

    async def submit_task(
        self,
        prompt: str,
        *,
        chat_session_id: str | None = None,
        model: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> TaskHandle:
        if not prompt.strip():
            raise SessionError("prompt must be non-empty")

        active_chat_session_id = chat_session_id
        if active_chat_session_id is None:
            active_chat_session_id = await self.ensure_chat_session()
        else:
            self.set_active_chat_session(active_chat_session_id)

        await self.send_message_async(
            prompt,
            session_id=active_chat_session_id,
            model=model,
        )
        task_handle = TaskHandle(
            id=self._make_task_id(active_chat_session_id),
            chat_session_id=active_chat_session_id,
            prompt=prompt,
            created_at=datetime.now(timezone.utc),
            metadata=dict(metadata or {}),
        )
        self._tasks[task_handle.id] = _TaskState(handle=task_handle)
        return task_handle

    def register_task(
        self,
        task_id: str,
        *,
        chat_session_id: str,
        prompt: str = "",
        created_at: datetime | None = None,
        metadata: dict[str, str] | None = None,
        status: TaskStatus = "pending",
    ) -> TaskHandle:
        resolved_task_id = task_id.strip()
        resolved_chat_session_id = chat_session_id.strip()
        if not resolved_task_id:
            raise SessionError("task_id must be non-empty")
        if not resolved_chat_session_id:
            raise SessionError("chat_session_id must be non-empty")
        handle = TaskHandle(
            id=resolved_task_id,
            chat_session_id=resolved_chat_session_id,
            prompt=prompt,
            created_at=created_at or datetime.now(timezone.utc),
            metadata=dict(metadata or {}),
        )
        self._tasks[resolved_task_id] = _TaskState(handle=handle, status=status)
        return handle

    async def cancel_task(self, task_id: str) -> None:
        task = self._get_task_state(task_id)
        await self.abort(task.handle.chat_session_id)
        task.status = "cancelled"
        task.last_event_at = datetime.now(timezone.utc)

    async def stream_task(self, task_id: str) -> AsyncIterator[TaskEvent]:
        task = self._get_task_state(task_id)
        async for raw_event in self.stream_events():
            if not self._event_matches_chat_session(raw_event, task.handle.chat_session_id):
                continue
            structured = self._normalize_task_event(task, raw_event)
            task.last_event_at = structured.ts
            await task._queue.put(structured)
            yield structured
            if self._is_terminal_task_event(raw_event):
                if task.status == "running":
                    task.status = "completed"
                break

    async def wait_task(
        self,
        task_id: str,
        *,
        timeout: float = 900,
    ) -> TaskResult:
        task = self._get_task_state(task_id)
        if task.status in {"running", "pending"}:
            try:
                await asyncio.wait_for(self._drain_task_stream(task_id), timeout=timeout)
            except TimeoutError:
                task.status = "timed_out"
                task.last_error = f"Task {task_id} timed out after {timeout}s"
                return TaskResult(
                    task_id=task_id,
                    chat_session_id=task.handle.chat_session_id,
                    status=task.status,
                    response=task.final_response,
                    error=task.last_error,
                )
            except BaseException as exc:
                task.status = "failed"
                task.last_error = str(exc)
                return TaskResult(
                    task_id=task_id,
                    chat_session_id=task.handle.chat_session_id,
                    status=task.status,
                    response=task.final_response,
                    error=task.last_error,
                )

        if task.status == "running":
            task.status = "completed"

        if task.status == "completed":
            try:
                messages = await self.get_messages(task.handle.chat_session_id)
                task.final_response = self.extract_response(messages)
            except BaseException as exc:
                task.status = "failed"
                task.last_error = str(exc)

        return TaskResult(
            task_id=task_id,
            chat_session_id=task.handle.chat_session_id,
            status=task.status,
            response=task.final_response,
            error=task.last_error,
        )

    async def get_task_changes(self, task_id: str) -> list[TaskFileChange]:
        task = self._get_task_state(task_id)
        return list(task.file_changes)

    async def get_task_diff(self, task_id: str) -> list[TaskDiffEntry]:
        task = self._get_task_state(task_id)
        raw_entries = await self.get_session_diff(task.handle.chat_session_id)
        entries: list[TaskDiffEntry] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path", ""))
            operation = str(entry.get("op") or entry.get("status") or "change")
            entries.append(
                TaskDiffEntry(
                    task_id=task_id,
                    chat_session_id=task.handle.chat_session_id,
                    path=path,
                    operation=operation,
                    raw=entry,
                )
            )
        return entries

    async def list_task_artifacts(self, task_id: str) -> list[TaskArtifact]:
        task = self._get_task_state(task_id)
        artifacts: list[TaskArtifact] = [
            TaskArtifact(
                id=f"{task_id}:messages",
                task_id=task_id,
                kind="messages",
                name="chat_messages",
                metadata={"chat_session_id": task.handle.chat_session_id},
            ),
            TaskArtifact(
                id=f"{task_id}:diff",
                task_id=task_id,
                kind="diff",
                name="session_diff",
                metadata={"chat_session_id": task.handle.chat_session_id},
            ),
            TaskArtifact(
                id=f"{task_id}:file_changes",
                task_id=task_id,
                kind="file_changes",
                name="file_changes",
                metadata={"count": str(len(task.file_changes))},
            ),
        ]
        if task.final_response is not None:
            artifacts.append(
                TaskArtifact(
                    id=f"{task_id}:response",
                    task_id=task_id,
                    kind="response",
                    name="final_response",
                    metadata={"chars": str(len(task.final_response))},
                )
            )
        return artifacts

    def list_tasks(self) -> list[TaskHandle]:
        return [state.handle for state in self._tasks.values()]

    def get_task_status(self, task_id: str) -> TaskStatus:
        return self._get_task_state(task_id).status

    async def _drain_task_stream(self, task_id: str) -> None:
        async for _ in self.stream_task(task_id):
            pass

    def _get_task_state(self, task_id: str) -> _TaskState:
        task = self._tasks.get(task_id)
        if task is not None:
            return task

        restored = self._restore_task_from_id(task_id)
        if restored is None:
            raise SessionError(f"Unknown task_id: {task_id}")
        self._tasks[task_id] = restored
        task = restored
        return task

    @staticmethod
    def _encode_chat_session_id(chat_session_id: str) -> str:
        raw = chat_session_id.encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_chat_session_token(token: str) -> str | None:
        try:
            padding = "=" * ((4 - (len(token) % 4)) % 4)
            decoded = base64.urlsafe_b64decode(f"{token}{padding}".encode("ascii"))
            return decoded.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None

    def _make_task_id(self, chat_session_id: str) -> str:
        token = self._encode_chat_session_id(chat_session_id)
        return f"task_{token}_{uuid4().hex}"

    def _restore_task_from_id(self, task_id: str) -> _TaskState | None:
        if not task_id.startswith("task_"):
            return None
        _, _, remainder = task_id.partition("task_")
        token, separator, unique = remainder.partition("_")
        if not separator or not token or not unique:
            return None
        chat_session_id = self._decode_chat_session_token(token)
        if not chat_session_id:
            return None
        handle = TaskHandle(
            id=task_id,
            chat_session_id=chat_session_id,
            prompt="",
            created_at=datetime.now(timezone.utc),
            metadata={"restored": "true"},
        )
        return _TaskState(handle=handle, status="pending")

    def _normalize_task_event(self, task: _TaskState, raw_event: dict[str, Any]) -> TaskEvent:
        raw_type = str(raw_event.get("type", "runtime.event"))
        payload = dict(raw_event.get("properties", {}))
        event_type = "runtime_event"
        if raw_type == "message.part.delta":
            event_type = "message_delta"
            delta = payload.get("delta", payload.get("content", ""))
            payload = {"delta": delta, "raw_type": raw_type}
        elif raw_type == "session.status":
            event_type = "status"
            if payload.get("status") == "idle":
                task.status = "completed"
        elif raw_type == "question.asked":
            event_type = "question_asked"
            task.status = "blocked"
        else:
            classified = self.classify_file_event(raw_event)
            if classified is not None:
                event_type = "file_changed"
                payload = classified

        task.next_sequence += 1
        event = TaskEvent(
            id=f"{task.handle.id}_evt_{task.next_sequence}",
            type=event_type,
            ts=datetime.now(timezone.utc),
            worker_id=str(self.backend.sandbox_id),
            chat_session_id=task.handle.chat_session_id,
            task_id=task.handle.id,
            sequence=task.next_sequence,
            payload=payload,
        )
        task.events.append(event)
        if event_type == "file_changed":
            path = str(payload.get("path", "")).strip()
            operation = str(payload.get("op", "change")).strip() or "change"
            if path:
                task.file_changes.append(
                    TaskFileChange(
                        task_id=task.handle.id,
                        chat_session_id=task.handle.chat_session_id,
                        path=path,
                        operation=operation,
                        sequence=event.sequence,
                        ts=event.ts,
                    )
                )
        return event

    @staticmethod
    def _event_matches_chat_session(event: dict[str, Any], chat_session_id: str) -> bool:
        properties = event.get("properties", {})
        if not isinstance(properties, dict):
            return False
        candidates = (
            properties.get("sessionID"),
            properties.get("sessionId"),
            properties.get("session_id"),
            event.get("sessionID"),
            event.get("sessionId"),
            event.get("session_id"),
        )
        for candidate in candidates:
            if candidate is not None and str(candidate) == chat_session_id:
                return True
        # Some streams do not annotate chat session ids on every message.
        return event.get("type") == "message.part.delta"

    @staticmethod
    def _is_terminal_task_event(event: dict[str, Any]) -> bool:
        if event.get("type") != "session.status":
            return False
        properties = event.get("properties", {})
        return isinstance(properties, dict) and properties.get("status") == "idle"

    async def send_message(
        self,
        text: str,
        *,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
        on_event: EventCallback = None,
        timeout: float = 900,
    ) -> str:
        return await self.runtime.send_message(
            text,
            session_id=session_id,
            model=model,
            on_event=on_event,
            timeout=timeout,
        )

    async def send_message_async(
        self,
        text: str,
        *,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
    ) -> str:
        active_session_id = session_id
        if active_session_id is None:
            active_session_id = self._active_chat_session_id
        response = await self.runtime.send_message_async(
            text,
            session_id=active_session_id,
            model=model,
        )
        self._active_chat_session_id = response
        return response

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        async for event in self.runtime.stream_events():
            yield event

    async def abort(self, session_id: str) -> None:
        await self.runtime.abort(session_id)

    async def get_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self.runtime.get_messages(session_id, limit=limit)

    async def set_provider_auth(
        self,
        provider_id: str,
        *,
        key: str,
        auth_type: str = "api",
    ) -> None:
        await self.runtime.set_provider_auth(provider_id, key=key, auth_type=auth_type)

    async def list_files(self, path: str | None = None) -> list[dict[str, Any]]:
        return await self.runtime.list_files(path)

    async def get_file_tree(
        self,
        path: str | None = None,
        *,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        return await self.runtime.get_file_tree(path, max_depth=max_depth)

    async def read_file(self, path: str) -> dict[str, Any]:
        return await self.runtime.read_file(path)

    async def file_status(self) -> list[dict[str, Any]]:
        return await self.runtime.file_status()

    async def find_files(self, query: str) -> list[dict[str, Any]]:
        return await self.runtime.find_files(query)

    async def search_in_files(self, pattern: str) -> list[dict[str, Any]]:
        return await self.runtime.search_in_files(pattern)

    async def get_session_diff(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return await self.runtime.get_session_diff(session_id)

    async def delete(self) -> None:
        await self.runtime.delete()

    async def close(self) -> None:
        await self.runtime.close()

    async def __aenter__(self) -> XoltSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self.backend.owns_sandbox:
                await self.delete()
        finally:
            await self.close()

    @staticmethod
    def extract_text(message: dict[str, Any]) -> str:
        from xolt.runtimes.opencode.runtime import OpenCodeRuntimeHandle

        return OpenCodeRuntimeHandle.extract_text(message)

    @staticmethod
    def extract_response(messages: list[dict[str, Any]]) -> str:
        from xolt.runtimes.opencode.runtime import OpenCodeRuntimeHandle

        return OpenCodeRuntimeHandle.extract_response(messages)

    @staticmethod
    def classify_file_event(event: dict[str, Any]) -> dict[str, str] | None:
        from xolt.runtimes.opencode.runtime import OpenCodeRuntimeHandle

        return OpenCodeRuntimeHandle.classify_file_event(event)
