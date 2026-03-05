from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from xolt.exceptions import SessionError
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


@pytest.mark.asyncio
async def test_chat_session_management_helpers() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    runtime = make_runtime_handle()
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    assert await session.ensure_chat_session() == "chat-1"
    assert session.active_chat_session_id == "chat-1"
    assert await session.ensure_chat_session() == "chat-1"
    runtime.create_chat_session.assert_awaited_once()

    session.set_active_chat_session("chat-2")
    assert session.active_chat_session_id == "chat-2"
    with pytest.raises(SessionError, match="non-empty"):
        session.set_active_chat_session("")


@pytest.mark.asyncio
async def test_task_lifecycle_submit_stream_wait_and_cancel() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)

    async def stream_events() -> AsyncIterator[dict[str, object]]:
        yield {
            "type": "message.part.delta",
            "properties": {"sessionID": "chat-1", "delta": "Hello"},
        }
        yield {
            "type": "file.edited",
            "properties": {"sessionID": "chat-1", "file": "README.md"},
        }
        yield {
            "type": "session.status",
            "properties": {"sessionID": "chat-1", "status": "idle"},
        }

    runtime = SimpleNamespace(
        session_id="session-123",
        cmd_id="cmd-123",
        installed_skills=[],
        deployed_agents=[],
        create_chat_session=AsyncMock(return_value={"id": "chat-1"}),
        send_message_async=AsyncMock(return_value="chat-1"),
        stream_events=stream_events,
        get_messages=AsyncMock(
            return_value=[
                {
                    "info": {"role": "assistant"},
                    "parts": [{"type": "text", "text": "done"}],
                }
            ]
        ),
        get_session_diff=AsyncMock(return_value=[{"path": "README.md", "op": "edit"}]),
        abort=AsyncMock(),
        close=AsyncMock(),
    )
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    handle = await session.submit_task(
        "Implement the feature",
        metadata={"ticket": "ABC-123"},
    )
    assert handle.chat_session_id == "chat-1"
    assert handle.metadata == {"ticket": "ABC-123"}
    runtime.send_message_async.assert_awaited_once_with(
        "Implement the feature",
        session_id="chat-1",
        model=None,
    )

    events = [event async for event in session.stream_task(handle.id)]
    assert [event.type for event in events] == ["message_delta", "file_changed", "status"]
    assert events[0].task_id == handle.id
    assert events[1].payload == {"op": "edit", "path": "README.md"}
    assert session.get_task_status(handle.id) == "completed"
    changes = await session.get_task_changes(handle.id)
    assert len(changes) == 1
    assert changes[0].path == "README.md"
    assert changes[0].operation == "edit"
    diff = await session.get_task_diff(handle.id)
    assert len(diff) == 1
    assert diff[0].path == "README.md"
    assert diff[0].operation == "edit"

    result = await session.wait_task(handle.id)
    assert result.status == "completed"
    assert result.response == "done"
    artifacts = await session.list_task_artifacts(handle.id)
    assert {artifact.kind for artifact in artifacts} == {
        "messages",
        "diff",
        "file_changes",
        "response",
    }

    await session.cancel_task(handle.id)
    assert session.get_task_status(handle.id) == "cancelled"
    runtime.abort.assert_awaited_once_with("chat-1")

    resumed = [event async for event in session.stream_task_from(handle.id, from_sequence=2)]
    assert [event.sequence for event in resumed] == [3]


@pytest.mark.asyncio
async def test_task_helpers_raise_on_unknown_task_id() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    runtime = make_runtime_handle()
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    with pytest.raises(SessionError, match="Unknown task_id"):
        _ = session.get_task_status("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        await session.cancel_task("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        await session.wait_task("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        await session.get_task_changes("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        await session.get_task_diff("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        await session.list_task_artifacts("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        _ = session.is_task_blocked("missing")
    with pytest.raises(SessionError, match="Unknown task_id"):
        _ = session.get_task_blocker("missing")
    assert session.list_blocked_tasks() == []


@pytest.mark.asyncio
async def test_task_reconnect_reconstructs_from_task_id() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    runtime = make_runtime_handle()
    session_one = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    handle = await session_one.submit_task("Do something")
    assert handle.id.startswith("task_")

    runtime_two = make_runtime_handle()
    runtime_two.get_session_diff = AsyncMock(return_value=[{"path": "README.md", "op": "edit"}])
    session_two = XoltSession(
        backend=backend,
        runtime=runtime_two,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    diff = await session_two.get_task_diff(handle.id)
    assert len(diff) == 1
    assert diff[0].path == "README.md"
    runtime_two.get_session_diff.assert_awaited_once_with(handle.chat_session_id)

    artifacts = await session_two.list_task_artifacts(handle.id)
    kinds = {artifact.kind for artifact in artifacts}
    assert kinds == {"messages", "diff", "file_changes"}
    assert session_two.get_task_status(handle.id) == "pending"


@pytest.mark.asyncio
async def test_register_task_explicit_recovery() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    runtime = make_runtime_handle()
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    registered = session.register_task(
        "legacy-task-id",
        chat_session_id="chat-9",
        prompt="Legacy prompt",
        metadata={"source": "import"},
        status="running",
    )
    assert registered.id == "legacy-task-id"
    assert registered.chat_session_id == "chat-9"
    assert session.get_task_status("legacy-task-id") == "running"

    with pytest.raises(SessionError, match="task_id must be non-empty"):
        session.register_task("", chat_session_id="chat-9")
    with pytest.raises(SessionError, match="chat_session_id must be non-empty"):
        session.register_task("task-x", chat_session_id="")


@pytest.mark.asyncio
async def test_wait_task_recovers_when_stream_fails() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)

    async def broken_stream() -> AsyncIterator[dict[str, object]]:
        raise RuntimeError("stale stream")
        yield {}

    runtime = SimpleNamespace(
        session_id="session-123",
        cmd_id="cmd-123",
        installed_skills=[],
        deployed_agents=[],
        create_chat_session=AsyncMock(return_value={"id": "chat-1"}),
        send_message_async=AsyncMock(return_value="chat-1"),
        stream_events=broken_stream,
        get_messages=AsyncMock(
            return_value=[
                {
                    "info": {"role": "assistant"},
                    "parts": [{"type": "text", "text": "Recovered response"}],
                }
            ]
        ),
        abort=AsyncMock(),
        close=AsyncMock(),
    )
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    handle = await session.submit_task("Recover this task")
    result = await session.wait_task(handle.id)
    assert result.status == "completed"
    assert result.response == "Recovered response"


@pytest.mark.asyncio
async def test_blocked_task_helpers_and_resume() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)

    async def blocked_stream() -> AsyncIterator[dict[str, object]]:
        yield {
            "type": "question.asked",
            "properties": {
                "sessionID": "chat-1",
                "id": "q-1",
                "questions": ["Apply this migration?"],
            },
        }

    runtime = SimpleNamespace(
        session_id="session-123",
        cmd_id="cmd-123",
        installed_skills=[],
        deployed_agents=[],
        create_chat_session=AsyncMock(return_value={"id": "chat-1"}),
        send_message_async=AsyncMock(return_value="chat-1"),
        stream_events=blocked_stream,
        get_messages=AsyncMock(return_value=[]),
        get_session_diff=AsyncMock(return_value=[]),
        abort=AsyncMock(),
        close=AsyncMock(),
    )
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    handle = await session.submit_task("Apply migration")
    events = [event async for event in session.stream_task(handle.id)]
    assert [event.type for event in events] == ["question_asked"]
    assert session.is_task_blocked(handle.id) is True

    blocker = session.get_task_blocker(handle.id)
    assert blocker is not None
    assert blocker.question_id == "q-1"
    assert blocker.questions == ["Apply this migration?"]

    result = await session.wait_task(handle.id)
    assert result.status == "blocked"

    artifacts = await session.list_task_artifacts(handle.id)
    assert "blocker" in {artifact.kind for artifact in artifacts}
    assert session.list_blocked_tasks() == [handle]

    resumed_handle = await session.resume_blocked_task(handle.id, "Yes, apply it.")
    assert resumed_handle.id == handle.id
    assert session.get_task_status(handle.id) == "running"
    runtime.send_message_async.assert_awaited_with(
        "Yes, apply it.",
        session_id="chat-1",
        model=None,
    )
    assert session.get_task_blocker(handle.id) is None

    with pytest.raises(SessionError, match="is not blocked"):
        await session.resume_blocked_task(handle.id, "Again")
    with pytest.raises(SessionError, match="answer must be non-empty"):
        # force blocked again for validation path
        session.register_task("task_x", chat_session_id="chat-1", status="blocked")
        await session.resume_blocked_task("task_x", "")


@pytest.mark.asyncio
async def test_multi_turn_multi_task_workflow() -> None:
    backend = SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True)
    stream_batches: list[list[dict[str, object]]] = [
        [
            {
                "type": "message.part.delta",
                "properties": {"sessionID": "chat-1", "delta": "First "},
            },
            {
                "type": "session.status",
                "properties": {"sessionID": "chat-1", "status": "idle"},
            },
        ],
        [
            {
                "type": "message.part.delta",
                "properties": {"sessionID": "chat-1", "delta": "Second "},
            },
            {
                "type": "file.edited",
                "properties": {"sessionID": "chat-1", "file": "src/main.py"},
            },
            {
                "type": "session.status",
                "properties": {"sessionID": "chat-1", "status": "idle"},
            },
        ],
    ]

    async def stream_events() -> AsyncIterator[dict[str, object]]:
        if not stream_batches:
            return
        for event in stream_batches.pop(0):
            yield event

    runtime = SimpleNamespace(
        session_id="session-123",
        cmd_id="cmd-123",
        installed_skills=[],
        deployed_agents=[],
        create_chat_session=AsyncMock(return_value={"id": "chat-1"}),
        send_message_async=AsyncMock(return_value="chat-1"),
        stream_events=stream_events,
        get_messages=AsyncMock(
            side_effect=[
                [
                    {
                        "info": {"role": "assistant"},
                        "parts": [{"type": "text", "text": "first done"}],
                    }
                ],
                [
                    {
                        "info": {"role": "assistant"},
                        "parts": [{"type": "text", "text": "second done"}],
                    }
                ],
            ]
        ),
        get_session_diff=AsyncMock(return_value=[{"path": "src/main.py", "op": "edit"}]),
        abort=AsyncMock(),
        close=AsyncMock(),
    )
    session = XoltSession(
        backend=backend,
        runtime=runtime,
        backend_adapter=SimpleNamespace(),
        runtime_adapter=SimpleNamespace(),
    )

    chat_id = await session.ensure_chat_session(title="multi-turn")
    first = await session.submit_task("Task 1", chat_session_id=chat_id)
    second = await session.submit_task("Task 2", chat_session_id=chat_id)

    first_events = [event async for event in session.stream_task(first.id)]
    second_events = [event async for event in session.stream_task(second.id)]
    first_result = await session.wait_task(first.id)
    second_result = await session.wait_task(second.id)

    assert first.chat_session_id == second.chat_session_id == "chat-1"
    assert [event.type for event in first_events] == ["message_delta", "status"]
    assert [event.type for event in second_events] == ["message_delta", "file_changed", "status"]
    assert first_result.response == "first done"
    assert second_result.response == "second done"
    changes = await session.get_task_changes(second.id)
    assert len(changes) == 1
    assert changes[0].path == "src/main.py"
