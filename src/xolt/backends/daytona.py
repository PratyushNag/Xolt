# SPDX-License-Identifier: Apache-2.0

"""Daytona backend adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, cast

from daytona import AsyncDaytona, CreateSandboxFromImageParams, Image

from xolt.backends.base import PreviewAccess
from xolt.exceptions import BackendProvisionError


@dataclass
class DaytonaHandle:
    """Concrete backend handle backed by Daytona."""

    daytona: Any
    sandbox: Any
    owns_sandbox: bool = True
    _closed: bool = False

    @property
    def sandbox_id(self) -> str:
        return str(self.sandbox.id)

    async def get_preview_access(self, port: int) -> PreviewAccess:
        preview_link = await self.sandbox.get_preview_link(port)
        return PreviewAccess(url=str(preview_link.url), token=str(preview_link.token))

    async def delete(self) -> None:
        await self.daytona.delete(self.sandbox)

    async def close(self) -> None:
        if not self._closed:
            await self.daytona.close()
            self._closed = True


class DaytonaBackend:
    """Provision execution environments in Daytona."""

    name = "daytona"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        image: str = "node:20-bookworm",
        create_timeout: int = 120,
    ) -> None:
        self.api_key = api_key
        self.image = image
        self.create_timeout = create_timeout

    def _client_kwargs(self) -> dict[str, str]:
        if self.api_key is not None:
            return {"api_key": self.api_key}
        if not os.environ.get("DAYTONA_API_KEY"):
            raise BackendProvisionError(
                "No Daytona API key provided. Pass api_key= or set DAYTONA_API_KEY."
            )
        return {}

    async def create(self) -> DaytonaHandle:
        daytona: AsyncDaytona | None = None
        try:
            daytona = cast(Any, AsyncDaytona)(**self._client_kwargs())
            sandbox = await daytona.create(
                CreateSandboxFromImageParams(image=Image.base(self.image)),
                timeout=self.create_timeout,
            )
            return DaytonaHandle(daytona=daytona, sandbox=sandbox, owns_sandbox=True)
        except Exception as exc:
            if daytona is not None:
                await cast(Any, daytona).close()
            raise BackendProvisionError(f"Failed to create Daytona sandbox: {exc}") from exc

    async def attach(self, sandbox_id: str) -> DaytonaHandle:
        daytona: AsyncDaytona | None = None
        try:
            daytona = cast(Any, AsyncDaytona)(**self._client_kwargs())
            sandbox = await daytona.get(sandbox_id)
            return DaytonaHandle(daytona=daytona, sandbox=sandbox, owns_sandbox=False)
        except Exception as exc:
            if daytona is not None:
                await cast(Any, daytona).close()
            raise BackendProvisionError(
                f"Failed to attach to Daytona sandbox {sandbox_id}: {exc}"
            ) from exc
