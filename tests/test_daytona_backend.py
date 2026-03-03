from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xolt.backends.daytona import DaytonaBackend, DaytonaHandle
from xolt.exceptions import BackendProvisionError


@pytest.mark.asyncio
async def test_daytona_handle_helpers() -> None:
    sandbox = MagicMock()
    sandbox.id = "sandbox-123"
    sandbox.get_preview_link = AsyncMock(
        return_value=SimpleNamespace(url="https://preview.example.com", token="tok")
    )
    daytona = AsyncMock()
    handle = DaytonaHandle(daytona=daytona, sandbox=sandbox)

    assert handle.sandbox_id == "sandbox-123"
    preview = await handle.get_preview_access(3000)
    assert preview.url == "https://preview.example.com"
    assert preview.token == "tok"
    await handle.delete()
    daytona.delete.assert_awaited_once_with(sandbox)
    await handle.close()
    await handle.close()
    daytona.close.assert_awaited_once()


def test_client_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DaytonaBackend(api_key="key")._client_kwargs() == {"api_key": "key"}
    monkeypatch.setenv("DAYTONA_API_KEY", "env-key")
    assert DaytonaBackend()._client_kwargs() == {}
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    with pytest.raises(BackendProvisionError, match="No Daytona API key"):
        DaytonaBackend()._client_kwargs()


@pytest.mark.asyncio
async def test_create_and_attach_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "env-key")
    sandbox = SimpleNamespace(id="sandbox-123")
    client = AsyncMock()
    client.create = AsyncMock(return_value=sandbox)
    client.get = AsyncMock(return_value=sandbox)

    with (
        patch("xolt.backends.daytona.AsyncDaytona", return_value=client),
        patch("xolt.backends.daytona.Image") as image,
        patch("xolt.backends.daytona.CreateSandboxFromImageParams", side_effect=lambda **kwargs: kwargs),
    ):
        image.base.return_value = "image"
        backend = DaytonaBackend(image="custom-image", create_timeout=12)
        created = await backend.create()
        attached = await backend.attach("sandbox-123")

    assert created.owns_sandbox is True
    assert attached.owns_sandbox is False
    image.base.assert_called_once_with("custom-image")
    client.create.assert_awaited_once()
    client.get.assert_awaited_once_with("sandbox-123")


@pytest.mark.asyncio
async def test_create_and_attach_wrap_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "env-key")
    client = AsyncMock()
    client.create = AsyncMock(side_effect=RuntimeError("create failed"))
    client.get = AsyncMock(side_effect=RuntimeError("attach failed"))

    with (
        patch("xolt.backends.daytona.AsyncDaytona", return_value=client),
        patch("xolt.backends.daytona.Image") as image,
        patch("xolt.backends.daytona.CreateSandboxFromImageParams", side_effect=lambda **kwargs: kwargs),
    ):
        image.base.return_value = "image"
        backend = DaytonaBackend()
        with pytest.raises(BackendProvisionError, match="Failed to create Daytona sandbox"):
            await backend.create()
        with pytest.raises(BackendProvisionError, match="Failed to attach to Daytona sandbox"):
            await backend.attach("sandbox-123")

    assert client.close.await_count == 2
