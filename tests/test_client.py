from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xolt.exceptions import FileError, MessageError, SessionError, StreamError
from xolt.runtimes.opencode.client import AUTH_HEADER, OpenCodeClient


@pytest.fixture()
def client() -> OpenCodeClient:
    return OpenCodeClient(base_url="https://preview.example.com/", token="tok-123")


def _mock_response(*, status: int = 200, text: str = "", json_data: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    response.text = AsyncMock(return_value=text if json_data is None else json.dumps(json_data))
    response.request_info = MagicMock()
    response.history = ()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_headers_include_auth(client: OpenCodeClient) -> None:
    headers = client._headers()
    assert headers[AUTH_HEADER] == "tok-123"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_request_returns_json(client: OpenCodeClient) -> None:
    with patch.object(client, "_get_session") as get_session:
        session = AsyncMock()
        session.request = MagicMock(return_value=_mock_response(json_data={"id": "s1"}))
        get_session.return_value = session
        assert await client._request("GET", "/session/s1") == {"id": "s1"}


@pytest.mark.asyncio
async def test_request_wraps_http_error(client: OpenCodeClient) -> None:
    with patch.object(client, "_get_session") as get_session:
        session = AsyncMock()
        session.request = MagicMock(return_value=_mock_response(status=500, text="boom"))
        get_session.return_value = session
        with pytest.raises(SessionError, match="HTTP GET /bad failed"):
            await client._request("GET", "/bad")


@pytest.mark.asyncio
async def test_send_message_async_wraps_errors(client: OpenCodeClient) -> None:
    with (
        patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            side_effect=SessionError("nope"),
        ),
        pytest.raises(MessageError, match="Failed to send async message"),
    ):
        await client.send_message_async("s1", "hello")


@pytest.mark.asyncio
async def test_file_operations_validate_shapes(client: OpenCodeClient) -> None:
    with (
        patch.object(client, "_request", new_callable=AsyncMock, return_value={"bad": True}),
        pytest.raises(FileError, match="Unexpected response"),
    ):
        await client.list_files("/root")


@pytest.mark.asyncio
async def test_stream_events_yields_json_events(client: OpenCodeClient) -> None:
    lines = [
        b'data: {"type": "server.connected"}\n',
        b"\n",
        b'data: {"type": "message.created"}\n',
    ]

    async def iter_lines():
        for line in lines:
            yield line

    session = AsyncMock()
    response = AsyncMock()
    response.status = 200
    response.content = iter_lines()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=cm)

    with patch.object(client, "_get_session", new_callable=AsyncMock, return_value=session):
        events = [event async for event in client.stream_events()]
    assert [event["type"] for event in events] == ["server.connected", "message.created"]


@pytest.mark.asyncio
async def test_stream_events_raises_on_http_error(client: OpenCodeClient) -> None:
    session = AsyncMock()
    response = AsyncMock()
    response.status = 500
    response.text = AsyncMock(return_value="bad")
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=cm)

    with (
        patch.object(client, "_get_session", new_callable=AsyncMock, return_value=session),
        pytest.raises(StreamError, match="SSE connection failed"),
    ):
        async for _ in client.stream_events():
            pass
