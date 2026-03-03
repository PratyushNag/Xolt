from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from xolt.session import XoltSession


def make_runtime_handle() -> SimpleNamespace:
    async def stream_events() -> AsyncIterator[dict[str, str]]:
        yield {"type": "event"}

    return SimpleNamespace(
        session_id="session-123",
        cmd_id="cmd-123",
        installed_skills=["browser-use/browser-use"],
        deployed_agents=["reviewer"],
        preview_url=AsyncMock(return_value="https://preview.example.com"),
        add_skill=AsyncMock(return_value=True),
        add_skills=AsyncMock(return_value=(["browser-use/browser-use"], ["bad/skill"])),
        list_skills=AsyncMock(return_value=["browser-use"]),
        reload_runtime=AsyncMock(),
        add_agent=AsyncMock(),
        remove_agent=AsyncMock(),
        list_agents=AsyncMock(return_value=["reviewer"]),
        create_chat_session=AsyncMock(return_value={"id": "chat-1"}),
        list_chat_sessions=AsyncMock(return_value=[{"id": "chat-1"}]),
        send_message=AsyncMock(return_value="hello"),
        send_message_async=AsyncMock(return_value="chat-1"),
        stream_events=stream_events,
        abort=AsyncMock(),
        get_messages=AsyncMock(return_value=[{"id": "m1"}]),
        set_provider_auth=AsyncMock(),
        list_files=AsyncMock(return_value=[{"path": "."}]),
        get_file_tree=AsyncMock(return_value=[{"path": ".", "children": []}]),
        read_file=AsyncMock(return_value={"path": "README.md", "content": "hi"}),
        file_status=AsyncMock(return_value=[{"path": "README.md", "status": "M"}]),
        find_files=AsyncMock(return_value=[{"path": "README.md"}]),
        search_in_files=AsyncMock(return_value=[{"path": "README.md", "line": 1}]),
        get_session_diff=AsyncMock(return_value=[{"path": "README.md", "op": "edit"}]),
        delete=AsyncMock(),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_create_and_attach_build_xolt_session() -> None:
    backend_handle = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    runtime_handle = make_runtime_handle()
    backend = SimpleNamespace(
        create=AsyncMock(return_value=backend_handle),
        attach=AsyncMock(return_value=backend_handle),
    )
    runtime = SimpleNamespace(
        start=AsyncMock(return_value=runtime_handle),
        attach=AsyncMock(return_value=runtime_handle),
    )

    created = await XoltSession.create(backend=backend, runtime=runtime)
    attached = await XoltSession.attach(
        "sandbox-123",
        backend=backend,
        runtime=runtime,
        session_id="session-123",
        cmd_id="cmd-123",
    )

    assert created.backend is backend_handle
    assert created.runtime is runtime_handle
    backend.create.assert_awaited_once()
    runtime.start.assert_awaited_once_with(backend_handle)
    backend.attach.assert_awaited_once_with("sandbox-123")
    runtime.attach.assert_awaited_once_with(
        backend_handle,
        session_id="session-123",
        cmd_id="cmd-123",
    )
    assert attached.runtime is runtime_handle


@pytest.mark.asyncio
async def test_properties_and_runtime_delegates() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    runtime = make_runtime_handle()
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    assert session.session_id == "session-123"
    assert session.cmd_id == "cmd-123"
    assert session.installed_skills == ["browser-use/browser-use"]
    assert session.deployed_agents == ["reviewer"]
    assert await session.preview_url() == "https://preview.example.com"
    assert await session.add_skill("browser-use/browser-use", reload=False) is True
    assert await session.add_skills(["browser-use/browser-use"], reload=False) == (
        ["browser-use/browser-use"],
        ["bad/skill"],
    )
    assert await session.list_skills() == ["browser-use"]
    await session.reload_runtime()
    await session.add_agent("reviewer", {"prompt": "Prompt"}, reload=False)
    await session.remove_agent("reviewer", reload=False)
    assert await session.list_agents() == ["reviewer"]
    assert await session.create_chat_session(title="Title") == {"id": "chat-1"}
    assert await session.list_chat_sessions() == [{"id": "chat-1"}]
    assert (
        await session.send_message(
            "hello",
            session_id="chat-1",
            model={"provider": "x", "name": "y"},
            timeout=1,
        )
        == "hello"
    )
    assert (
        await session.send_message_async(
            "hello",
            session_id="chat-1",
            model={"provider": "x", "name": "y"},
        )
        == "chat-1"
    )
    assert [event async for event in session.stream_events()] == [{"type": "event"}]
    await session.abort("chat-1")
    assert await session.get_messages("chat-1", limit=5) == [{"id": "m1"}]
    await session.set_provider_auth("openai", key="secret", auth_type="api")
    assert await session.list_files(".") == [{"path": "."}]
    assert await session.get_file_tree(".", max_depth=1) == [{"path": ".", "children": []}]
    assert await session.read_file("README.md") == {"path": "README.md", "content": "hi"}
    assert await session.file_status() == [{"path": "README.md", "status": "M"}]
    assert await session.find_files("README") == [{"path": "README.md"}]
    assert await session.search_in_files("hello") == [{"path": "README.md", "line": 1}]
    assert await session.get_session_diff("chat-1") == [{"path": "README.md", "op": "edit"}]
    await session.delete()
    await session.close()

    runtime.preview_url.assert_awaited_once()
    runtime.add_skill.assert_awaited_once_with("browser-use/browser-use", reload=False)
    runtime.add_skills.assert_awaited_once_with(["browser-use/browser-use"], reload=False)
    runtime.reload_runtime.assert_awaited_once()
    runtime.add_agent.assert_awaited_once_with("reviewer", {"prompt": "Prompt"}, reload=False)
    runtime.remove_agent.assert_awaited_once_with("reviewer", reload=False)
    runtime.create_chat_session.assert_awaited_once_with(title="Title")
    runtime.list_chat_sessions.assert_awaited_once()
    runtime.send_message.assert_awaited_once()
    runtime.send_message_async.assert_awaited_once()
    runtime.abort.assert_awaited_once_with("chat-1")
    runtime.get_messages.assert_awaited_once_with("chat-1", limit=5)
    runtime.set_provider_auth.assert_awaited_once_with("openai", key="secret", auth_type="api")
    runtime.list_files.assert_awaited_once_with(".")
    runtime.get_file_tree.assert_awaited_once_with(".", max_depth=1)
    runtime.read_file.assert_awaited_once_with("README.md")
    runtime.file_status.assert_awaited_once()
    runtime.find_files.assert_awaited_once_with("README")
    runtime.search_in_files.assert_awaited_once_with("hello")
    runtime.get_session_diff.assert_awaited_once_with("chat-1")
    runtime.delete.assert_awaited_once()
    runtime.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_manager_deletes_owned_backend() -> None:
    owned_backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    owned_runtime = make_runtime_handle()
    owned_session = XoltSession(
        backend=owned_backend,
        runtime=owned_runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    async with owned_session as active:
        assert active is owned_session

    owned_runtime.delete.assert_awaited_once()
    owned_runtime.close.assert_awaited_once()

    attached_backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=False)
    attached_runtime = make_runtime_handle()
    attached_session = XoltSession(
        backend=attached_backend,
        runtime=attached_runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    async with attached_session:
        pass

    attached_runtime.delete.assert_not_awaited()
    attached_runtime.close.assert_awaited_once()


def test_static_helpers_delegate_to_runtime_handle() -> None:
    message = {"parts": [{"type": "text", "text": "hello"}]}
    messages = [{"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "hello"}]}]
    file_event = {"type": "file.edited", "properties": {"file": "README.md"}}

    assert XoltSession.extract_text(message) == "hello"
    assert XoltSession.extract_response(messages) == "hello"
    assert XoltSession.classify_file_event(file_event) == {"op": "edit", "path": "README.md"}
