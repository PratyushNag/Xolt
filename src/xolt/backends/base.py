# SPDX-License-Identifier: Apache-2.0

"""Execution backend interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PreviewAccess:
    """Preview endpoint metadata for a runtime port."""

    url: str
    token: str


class BackendHandle(Protocol):
    """Live backend connection bound to a provisioned sandbox."""

    sandbox: Any
    sandbox_id: str
    owns_sandbox: bool

    async def get_preview_access(self, port: int) -> PreviewAccess:
        """Return preview access details for the given port."""

    async def delete(self) -> None:
        """Delete the provisioned sandbox."""

    async def close(self) -> None:
        """Close local client resources without deleting the sandbox."""


class ExecutionBackend(Protocol):
    """Backend adapter interface."""

    name: str

    async def create(self) -> BackendHandle:
        """Provision a new backend handle."""

    async def attach(self, sandbox_id: str) -> BackendHandle:
        """Attach to an existing backend handle."""
