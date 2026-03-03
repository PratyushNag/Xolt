# SPDX-License-Identifier: Apache-2.0

"""Managed runtime interfaces."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol, TypeAlias

from xolt.backends.base import BackendHandle

RuntimeEvent: TypeAlias = dict[str, Any]
EventCallback: TypeAlias = Callable[[RuntimeEvent], Awaitable[None] | None] | None


class RuntimeHandle(Protocol):
    """Live runtime bound to a backend handle."""

    session_id: str
    cmd_id: str
    installed_skills: list[str]
    deployed_agents: list[str]

    async def preview_url(self) -> str:
        """Return the public preview URL for the runtime."""

    async def delete(self) -> None:
        """Delete remote backend resources owned by this handle."""

    async def close(self) -> None:
        """Release local resources held by this runtime handle."""

    async def add_skill(self, skill_source: str, *, reload: bool = True) -> bool:
        """Install a single skill."""

    async def add_skills(
        self,
        skills: list[str],
        *,
        reload: bool = True,
    ) -> tuple[list[str], list[str]]:
        """Install multiple skills."""

    async def list_skills(self) -> list[str]:
        """List installed skills."""

    async def reload_runtime(self) -> None:
        """Reload runtime state after changes."""

    async def add_agent(self, name: str, config: Any, *, reload: bool = True) -> None:
        """Add a runtime agent."""

    async def remove_agent(self, name: str, *, reload: bool = True) -> None:
        """Remove a runtime agent."""

    async def list_agents(self) -> list[str]:
        """List runtime agents."""

    async def create_chat_session(self, *, title: str | None = None) -> dict[str, Any]:
        """Create a runtime chat session."""

    async def list_chat_sessions(self) -> list[dict[str, Any]]:
        """List runtime chat sessions."""

    async def send_message(
        self,
        text: str,
        *,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
        on_event: EventCallback = None,
        timeout: float = 900,
    ) -> str:
        """Send a blocking message."""

    async def send_message_async(
        self,
        text: str,
        *,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
    ) -> str:
        """Send a non-blocking message."""

    def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        """Stream runtime events."""

    async def abort(self, session_id: str) -> None:
        """Abort a chat session."""

    async def get_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return chat messages."""

    async def set_provider_auth(
        self,
        provider_id: str,
        *,
        key: str,
        auth_type: str = "api",
    ) -> None:
        """Set provider auth."""

    async def list_files(self, path: str | None = None) -> list[dict[str, Any]]:
        """List runtime files."""

    async def get_file_tree(
        self,
        path: str | None = None,
        *,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """Return nested file tree."""

    async def read_file(self, path: str) -> dict[str, Any]:
        """Read a file."""

    async def file_status(self) -> list[dict[str, Any]]:
        """Return file status."""

    async def find_files(self, query: str) -> list[dict[str, Any]]:
        """Find files by query."""

    async def search_in_files(self, pattern: str) -> list[dict[str, Any]]:
        """Search file contents."""

    async def get_session_diff(
        self,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a session diff."""


class ManagedRuntime(Protocol):
    """Runtime adapter interface."""

    name: str

    async def start(self, backend: BackendHandle) -> RuntimeHandle:
        """Start a runtime in a newly provisioned backend handle."""

    async def attach(
        self,
        backend: BackendHandle,
        *,
        session_id: str = "",
        cmd_id: str = "",
    ) -> RuntimeHandle:
        """Attach to an existing runtime in a backend handle."""
