# SPDX-License-Identifier: Apache-2.0

"""Public Xolt session object."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from xolt.backends.base import BackendHandle, ExecutionBackend
from xolt.runtimes.base import EventCallback, ManagedRuntime, RuntimeHandle


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
        return await self.runtime.create_chat_session(title=title)

    async def list_chat_sessions(self) -> list[dict[str, Any]]:
        return await self.runtime.list_chat_sessions()

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
        return await self.runtime.send_message_async(
            text,
            session_id=session_id,
            model=model,
        )

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
