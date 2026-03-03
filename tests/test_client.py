from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from xolt.exceptions import FileError, MessageError, SessionError, StreamError
from xolt.runtimes.opencode.client import AUTH_HEADER, OpenCodeClient


class ResponseContext:
    def __init__(self, response: object) -> None:
        self.response = response

    async def __aenter__(self) -> object:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeResponse:
    def __init__(
        self, *, status: int = 200, text: str = "", content: AsyncIterator[bytes] | None = None
    ):
        self.status = status
        self._text = text
        self.content = content if content is not None else self._empty_content()
        self.request_info = MagicMock()
        self.history = ()

    async def text(self) -> str:
        return self._text

    async def _empty_content(self) -> AsyncIterator[bytes]:
        if False:
            yield b""


@pytest.mark.asyncio
async def test_headers_session_lifecycle_and_close() -> None:
    created_session = MagicMock()
    created_session.closed = False
    created_session.close = AsyncMock()

    with patch("xolt.runtimes.opencode.client.aiohttp.ClientSession", return_value=created_session):
        client = OpenCodeClient("https://preview.example.com/", "token-123")
        assert client._headers() == {
            AUTH_HEADER: "token-123",
            "Content-Type": "application/json",
        }
        session = await client._get_session()
        assert session is created_session
        reused = await client._get_session()
        assert reused is created_session
        await client.close()

    created_session.close.assert_awaited_once()
    assert client._session is None


@pytest.mark.asyncio
async def test_request_success_204_http_error_and_timeout() -> None:
    client = OpenCodeClient("https://preview.example.com", "token")
    session = MagicMock()
    session.closed = False
    client._session = session

    session.request = MagicMock(
        return_value=ResponseContext(FakeResponse(text=json.dumps({"ok": True})))
    )
    assert await client._request("GET", "/ok") == {"ok": True}

    session.request = MagicMock(return_value=ResponseContext(FakeResponse(status=204)))
    assert await client._request("POST", "/empty") is None

    session.request = MagicMock(
        return_value=ResponseContext(FakeResponse(status=400, text="bad request"))
    )
    with pytest.raises(SessionError, match="HTTP GET /bad failed"):
        await client._request("GET", "/bad")

    session.request = MagicMock(side_effect=TimeoutError())
    with pytest.raises(SessionError, match="timed out after 7s"):
        await client._request("GET", "/slow", timeout=7)


@pytest.mark.asyncio
async def test_session_and_message_methods() -> None:
    client = OpenCodeClient("https://preview.example.com", "token")
    client._request = AsyncMock(
        side_effect=[
            {"id": "chat-1"},
            [{"id": "chat-1"}],
            None,
            None,
            [{"id": "m1"}],
            [{"id": "m2"}],
        ]
    )

    assert await client.create_session(title="Title") == {"id": "chat-1"}
    assert await client.list_sessions() == [{"id": "chat-1"}]
    await client.abort_session("chat-1")
    await client.send_message_async("chat-1", "hello", model={"provider": "x", "name": "y"})
    assert await client.list_messages("chat-1") == [{"id": "m1"}]
    assert await client.list_messages("chat-1", limit=5) == [{"id": "m2"}]

    assert client._request.await_args_list[0].kwargs["json_body"] == {"title": "Title"}
    assert client._request.await_args_list[3].kwargs["json_body"] == {
        "parts": [{"type": "text", "text": "hello"}],
        "model": {"provider": "x", "name": "y"},
    }
    assert client._request.await_args_list[5].kwargs["params"] == {"limit": "5"}


@pytest.mark.asyncio
async def test_session_and_message_methods_wrap_bad_shapes_and_errors() -> None:
    client = OpenCodeClient("https://preview.example.com", "token")

    client._request = AsyncMock(return_value=[])
    with pytest.raises(SessionError, match="Unexpected response when creating session"):
        await client.create_session()

    client._request = AsyncMock(return_value={})
    with pytest.raises(SessionError, match="Unexpected response when listing sessions"):
        await client.list_sessions()

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(MessageError, match="Failed to send async message"):
        await client.send_message_async("chat-1", "hello")

    client._request = AsyncMock(return_value={})
    with pytest.raises(MessageError, match="Unexpected response for messages"):
        await client.list_messages("chat-1")


@pytest.mark.asyncio
async def test_file_methods_and_set_provider_auth() -> None:
    client = OpenCodeClient("https://preview.example.com", "token")
    client._request = AsyncMock(
        side_effect=[
            [{"path": "."}],
            {"path": "README.md"},
            [{"path": "README.md", "status": "M"}],
            [{"path": "README.md"}],
            [{"path": "README.md", "line": 1}],
            [{"path": "README.md", "op": "edit"}],
            None,
        ]
    )

    assert await client.list_files() == [{"path": "."}]
    assert await client.read_file("README.md") == {"path": "README.md"}
    assert await client.file_status() == [{"path": "README.md", "status": "M"}]
    assert await client.find_files("README") == [{"path": "README.md"}]
    assert await client.search_in_files("hello") == [{"path": "README.md", "line": 1}]
    assert await client.get_session_diff("chat-1") == [{"path": "README.md", "op": "edit"}]
    await client.set_provider_auth("openai", auth_type="api", key="secret")

    assert client._request.await_args_list[0].kwargs["params"] == {"path": "."}
    assert client._request.await_args_list[-1].kwargs["json_body"] == {
        "type": "api",
        "key": "secret",
    }


@pytest.mark.asyncio
async def test_file_methods_wrap_errors_and_bad_shapes() -> None:
    client = OpenCodeClient("https://preview.example.com", "token")

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(FileError, match="Failed to list files at src"):
        await client.list_files("src")

    client._request = AsyncMock(return_value={})
    with pytest.raises(FileError, match="Unexpected response when listing files"):
        await client.list_files()

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(FileError, match="Failed to read file README.md"):
        await client.read_file("README.md")

    client._request = AsyncMock(return_value=[])
    with pytest.raises(FileError, match="Unexpected response when reading file README.md"):
        await client.read_file("README.md")

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(FileError, match="Failed to get file status"):
        await client.file_status()

    client._request = AsyncMock(return_value={})
    with pytest.raises(FileError, match="Unexpected response when getting file status"):
        await client.file_status()

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(FileError, match="Failed to find files for 'README'"):
        await client.find_files("README")

    client._request = AsyncMock(return_value={})
    with pytest.raises(FileError, match="Unexpected response when finding files"):
        await client.find_files("README")

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(FileError, match="Failed to search for 'hello'"):
        await client.search_in_files("hello")

    client._request = AsyncMock(return_value={})
    with pytest.raises(FileError, match="Unexpected response when searching for 'hello'"):
        await client.search_in_files("hello")

    client._request = AsyncMock(side_effect=SessionError("boom"))
    with pytest.raises(FileError, match="Failed to get diff for session chat-1"):
        await client.get_session_diff("chat-1")

    client._request = AsyncMock(return_value={})
    with pytest.raises(FileError, match="Unexpected response for diff of session chat-1"):
        await client.get_session_diff("chat-1")


@pytest.mark.asyncio
async def test_stream_events_success_skips_invalid_and_wraps_errors() -> None:
    async def good_content() -> AsyncIterator[bytes]:
        yield b"event: ping\n"
        yield b"data: not-json\n"
        yield b'data: {"type": "session.status", "properties": {"status": "idle"}}\n'

    client = OpenCodeClient("https://preview.example.com", "token")
    session = MagicMock()
    session.closed = False
    session.get = MagicMock(return_value=ResponseContext(FakeResponse(content=good_content())))
    client._session = session

    events = [event async for event in client.stream_events()]
    assert events == [{"type": "session.status", "properties": {"status": "idle"}}]

    session.get = MagicMock(
        return_value=ResponseContext(FakeResponse(status=500, text="server error"))
    )
    with pytest.raises(StreamError, match="SSE connection failed"):
        [event async for event in client.stream_events()]

    session.get = MagicMock(side_effect=aiohttp.ClientError("broken"))
    with pytest.raises(StreamError, match="SSE stream error"):
        [event async for event in client.stream_events()]
