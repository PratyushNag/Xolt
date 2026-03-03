from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from xolt.exceptions import FileError, MessageError, QuestionAskedError
from xolt.runtimes.opencode.runtime import OpenCodeRuntime, OpenCodeRuntimeHandle


def make_client() -> SimpleNamespace:
    return SimpleNamespace(
        create_session=AsyncMock(return_value={"id": "chat-1"}),
        list_sessions=AsyncMock(return_value=[{"id": "chat-1"}]),
        send_message_async=AsyncMock(),
        list_messages=AsyncMock(
            return_value=[
                {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "done"}]}
            ]
        ),
        stream_events=None,
        abort_session=AsyncMock(),
        set_provider_auth=AsyncMock(),
        list_files=AsyncMock(return_value=[{"path": ".", "type": "file"}]),
        read_file=AsyncMock(return_value={"path": "README.md"}),
        file_status=AsyncMock(return_value=[{"path": "README.md", "status": "M"}]),
        find_files=AsyncMock(return_value=[{"path": "README.md"}]),
        search_in_files=AsyncMock(return_value=[{"path": "README.md", "line": 1}]),
        get_session_diff=AsyncMock(return_value=[{"path": "README.md", "op": "edit"}]),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_preview_and_get_client_cache(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(backend_handle, session_id="session-123", cmd_id="cmd-123")

    assert await handle.preview_url() == "https://preview.example.com"
    with patch("xolt.runtimes.opencode.runtime.OpenCodeClient") as client_cls:
        client = client_cls.return_value
        first = await handle._get_client()
        second = await handle._get_client()

    assert first is client
    assert second is client
    backend_handle.get_preview_access.assert_awaited()
    client_cls.assert_called_once_with(
        base_url="https://preview.example.com",
        token="preview-token",
    )


@pytest.mark.asyncio
async def test_skill_and_agent_management(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(
        backend_handle,
        session_id="session-123",
        cmd_id="cmd-123",
        installed_skills=["existing"],
        deployed_agents=["existing-agent"],
    )

    with (
        patch(
            "xolt.runtimes.opencode.runtime.install_skills",
            new=AsyncMock(return_value=(["new"], ["bad"])),
        ),
        patch("xolt.runtimes.opencode.runtime.dispose_all_instances", new=AsyncMock()) as dispose,
        patch("xolt.runtimes.opencode.runtime.list_skills", new=AsyncMock(return_value=["new"])),
        patch("xolt.runtimes.opencode.runtime.deploy_agent", new=AsyncMock()) as deploy,
        patch("xolt.runtimes.opencode.runtime.remove_agent_file", new=AsyncMock()) as remove,
        patch(
            "xolt.runtimes.opencode.runtime.list_deployed_agents",
            new=AsyncMock(return_value=["existing-agent"]),
        ),
    ):
        assert await handle.add_skill("new", reload=False) is True
        assert await handle.add_skills(["more"], reload=True) == (["new"], ["bad"])
        assert handle.installed_skills == ["existing", "new", "new"]
        assert await handle.list_skills() == ["new"]
        await handle.reload_runtime()
        await handle.add_agent("agent-a", {"prompt": "Prompt"}, reload=True)
        await handle.remove_agent("existing-agent", reload=True)
        assert await handle.list_agents() == ["existing-agent"]

    deploy.assert_awaited_once_with(handle.sandbox, "agent-a", {"prompt": "Prompt"})
    remove.assert_awaited_once_with(handle.sandbox, "existing-agent")
    assert "agent-a" in handle.deployed_agents
    assert "existing-agent" not in handle.deployed_agents
    assert dispose.await_count == 4


@pytest.mark.asyncio
async def test_check_and_dispose_paths(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(backend_handle, session_id="session-123", cmd_id="cmd-123")
    handle.sandbox.process.exec = AsyncMock(
        side_effect=[
            SimpleNamespace(exit_code=0, result="EXISTS"),
            SimpleNamespace(exit_code=0, result=""),
        ]
    )

    with patch("xolt.runtimes.opencode.runtime.dispose_all_instances", new=AsyncMock()) as dispose:
        assert await handle._check_and_dispose() is True
        assert await handle._check_and_dispose() is False

    assert dispose.await_count == 1

    handle.sandbox.process.exec = AsyncMock(side_effect=RuntimeError("boom"))
    assert await handle._check_and_dispose() is False


@pytest.mark.asyncio
async def test_chat_session_message_and_stream_delegates(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(backend_handle, session_id="session-123", cmd_id="cmd-123")
    client = make_client()

    async def stream_events() -> AsyncIterator[dict[str, str]]:
        yield {"type": "session.status", "properties": {"status": "idle"}}

    client.stream_events = stream_events
    handle._client = client
    handle._check_and_dispose = AsyncMock(side_effect=[False, True])
    handle._wait_for_idle = AsyncMock(return_value="streamed text")

    assert await handle.create_chat_session(title="Title") == {"id": "chat-1"}
    assert await handle.list_chat_sessions() == [{"id": "chat-1"}]
    assert (
        await handle.send_message(
            "hello",
            session_id="chat-1",
            model={"provider": "x", "name": "y"},
            timeout=1,
        )
        == "done"
    )
    assert await handle.send_message_async("hello") == "chat-1"
    assert [event async for event in handle.stream_events()] == [
        {"type": "session.status", "properties": {"status": "idle"}}
    ]
    await handle.abort("chat-1")
    assert await handle.get_messages("chat-1", limit=5) == [
        {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "done"}]}
    ]
    await handle.set_provider_auth("openai", key="secret", auth_type="api")

    client.create_session.assert_awaited()
    client.send_message_async.assert_awaited()
    client.abort_session.assert_awaited_once_with("chat-1")
    client.list_messages.assert_any_await("chat-1")
    client.set_provider_auth.assert_awaited_once_with("openai", auth_type="api", key="secret")


@pytest.mark.asyncio
async def test_wait_for_idle_handles_callbacks_and_questions(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(backend_handle, session_id="session-123", cmd_id="cmd-123")
    seen: list[str] = []

    async def callback(event: dict[str, object]) -> None:
        seen.append(str(event["type"]))

    async def idle_stream() -> AsyncIterator[dict[str, object]]:
        yield {"type": "message.part.delta", "properties": {"delta": "Hello "}}
        yield {"type": "message.part.delta", "properties": {"content": "world"}}
        yield {"type": "session.status", "properties": {"status": "idle"}}

    handle.stream_events = idle_stream
    assert await handle._wait_for_idle(on_event=callback) == "Hello world"
    assert seen == ["message.part.delta", "message.part.delta", "session.status"]

    async def question_stream() -> AsyncIterator[dict[str, object]]:
        yield {"type": "message.part.delta", "properties": {"delta": "partial"}}
        yield {
            "type": "question.asked",
            "properties": {"id": "q1", "sessionID": "s1", "questions": ["Continue?"]},
        }

    handle.stream_events = question_stream
    with pytest.raises(QuestionAskedError) as exc:
        await handle._wait_for_idle()
    assert exc.value.streamed_text == "partial"


@pytest.mark.asyncio
async def test_file_operations_tree_diff_close_and_helpers(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(backend_handle, session_id="session-123", cmd_id="cmd-123")
    client = make_client()
    handle._client = client

    async def fake_list_files(path: str | None = None) -> list[dict[str, object]]:
        if path is None:
            return [
                {"path": "src", "type": "directory"},
                {"path": "README.md", "type": "file"},
            ]
        if path == "src":
            return [{"path": "src/main.py", "type": "file"}]
        raise RuntimeError("unexpected path")

    handle.list_files = fake_list_files
    assert await handle.get_file_tree(max_depth=0) == [
        {"path": "src", "type": "directory"},
        {"path": "README.md", "type": "file"},
    ]
    assert await handle.get_file_tree(max_depth=1) == [
        {
            "path": "src",
            "type": "directory",
            "children": [{"path": "src/main.py", "type": "file"}],
        },
        {"path": "README.md", "type": "file"},
    ]

    async def broken_list_files(path: str | None = None) -> list[dict[str, object]]:
        if path is None:
            return [{"path": "src", "type": "directory"}]
        raise FileError("boom")

    handle.list_files = broken_list_files
    assert await handle.get_file_tree(max_depth=1) == [
        {"path": "src", "type": "directory", "children": []}
    ]

    handle.list_files = AsyncMock(return_value=[{"path": ".", "type": "file"}])
    assert await handle.list_files(".") == [{"path": ".", "type": "file"}]
    assert await handle.read_file("README.md") == {"path": "README.md"}
    assert await handle.file_status() == [{"path": "README.md", "status": "M"}]
    assert await handle.find_files("README") == [{"path": "README.md"}]
    assert await handle.search_in_files("hello") == [{"path": "README.md", "line": 1}]
    assert await handle.get_session_diff("chat-1") == [{"path": "README.md", "op": "edit"}]
    with pytest.raises(FileError, match="session_id is required"):
        await handle.get_session_diff()

    await handle.delete()
    await handle.close()
    client.close.assert_awaited_once()
    backend_handle.delete.assert_awaited_once()
    backend_handle.close.assert_awaited_once()

    assert (
        OpenCodeRuntimeHandle.extract_text({"parts": [{"type": "text", "text": "hello"}]})
        == "hello"
    )
    assert OpenCodeRuntimeHandle.extract_text({"parts": "nope"}) == "{'parts': 'nope'}"
    assert OpenCodeRuntimeHandle.extract_response([]) == "(no response)"
    with pytest.raises(MessageError, match="Agent error"):
        OpenCodeRuntimeHandle.extract_response(
            [{"info": {"role": "assistant", "error": "boom"}, "parts": []}]
        )
    assert (
        OpenCodeRuntimeHandle.extract_response(
            [{"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "hello"}]}]
        )
        == "hello"
    )
    assert OpenCodeRuntimeHandle._is_raw_fallback("") is True
    assert OpenCodeRuntimeHandle._is_raw_fallback("(no response)") is True
    assert OpenCodeRuntimeHandle._is_raw_fallback("{'info': 'x'}") is True
    assert OpenCodeRuntimeHandle._is_raw_fallback("hello") is False
    assert OpenCodeRuntimeHandle.classify_file_event(
        {"type": "file.edited", "properties": {"file": "README.md"}}
    ) == {"op": "edit", "path": "README.md"}
    assert OpenCodeRuntimeHandle.classify_file_event(
        {"type": "file.watcher.updated", "properties": {"event": "add", "file": "a.py"}}
    ) == {"op": "add", "path": "a.py"}
    assert (
        OpenCodeRuntimeHandle.classify_file_event(
            {"type": "file.watcher.updated", "properties": {"event": "unknown", "file": "a.py"}}
        )
        is None
    )
    assert OpenCodeRuntimeHandle.classify_file_event(
        {"type": "session.status", "properties": {"status": "idle"}}
    ) == {"op": "reconcile"}
    assert OpenCodeRuntimeHandle.classify_file_event({"type": "unknown", "properties": {}}) is None


@pytest.mark.asyncio
async def test_send_message_uses_streamed_fallback_and_cancels_on_error(backend_handle) -> None:
    handle = OpenCodeRuntimeHandle(backend_handle, session_id="session-123", cmd_id="cmd-123")
    client = make_client()
    client.list_messages = AsyncMock(return_value=[{"info": {"role": "assistant"}, "parts": "bad"}])
    handle._client = client
    handle._check_and_dispose = AsyncMock(return_value=False)
    handle._wait_for_idle = AsyncMock(return_value="streamed")

    assert await handle.send_message("hello", session_id="chat-1", timeout=1) == "streamed"

    async def fail_wait(*, on_event=None) -> str:
        raise RuntimeError("boom")

    handle._wait_for_idle = fail_wait
    with pytest.raises(RuntimeError, match="boom"):
        await handle.send_message("hello", session_id="chat-1", timeout=1)


@pytest.mark.asyncio
async def test_runtime_start_attach_and_failure_cleanup(backend_handle) -> None:
    runtime = OpenCodeRuntime(
        skills=["browser-use/browser-use"],
        agents={"daytona": {"prompt": "skip"}, "reviewer": {"prompt": "Prompt"}},
        port=4000,
    )
    backend_handle.sandbox.process.exec = AsyncMock(
        side_effect=[
            SimpleNamespace(exit_code=0, result="installed"),
            SimpleNamespace(exit_code=0, result="skills"),
            SimpleNamespace(exit_code=0, result="mkdir"),
            SimpleNamespace(exit_code=0, result="proxy"),
        ]
    )
    backend_handle.sandbox.process.create_session = AsyncMock()
    backend_handle.sandbox.process.execute_session_command = AsyncMock(
        return_value=SimpleNamespace(cmd_id="cmd-999")
    )

    with (
        patch("daytona.SessionExecuteRequest", side_effect=lambda **kwargs: kwargs),
        patch("xolt.runtimes.opencode.runtime.get_manage_skills_markdown", return_value="# skill"),
        patch("xolt.runtimes.opencode.runtime.get_proxy_script", return_value="console.log('x')"),
        patch(
            "xolt.runtimes.opencode.runtime.install_skills",
            new=AsyncMock(return_value=(["browser-use/browser-use"], [])),
        ),
        patch("xolt.runtimes.opencode.runtime.deploy_agent", new=AsyncMock()) as deploy,
        patch(
            "xolt.runtimes.opencode.runtime.build_opencode_config",
            new=AsyncMock(return_value=("X=1", {})),
        ),
    ):
        handle = await runtime.start(backend_handle)

    assert handle.cmd_id == "cmd-999"
    assert handle.port == 4000
    assert handle.installed_skills == ["browser-use/browser-use"]
    assert handle.deployed_agents == ["reviewer"]
    deploy.assert_awaited_once_with(backend_handle.sandbox, "reviewer", {"prompt": "Prompt"})
    assert backend_handle.sandbox.fs.upload_file.await_count == 2

    attached = await runtime.attach(backend_handle, session_id="s", cmd_id="c")
    assert attached.session_id == "s"
    assert attached.cmd_id == "c"

    failing_runtime = OpenCodeRuntime()
    backend_handle.delete.reset_mock()
    backend_handle.close.reset_mock()
    backend_handle.sandbox.process.exec = AsyncMock(
        return_value=SimpleNamespace(exit_code=1, result="install failed")
    )
    with pytest.raises(MessageError, match="Failed to install OpenCode"):
        await failing_runtime.start(backend_handle)
    backend_handle.delete.assert_awaited_once()
    backend_handle.close.assert_awaited_once()


def test_question_asked_error_exposes_context() -> None:
    exc = QuestionAskedError("q1", "s1", ["Continue?"], streamed_text="partial")
    assert exc.question_id == "q1"
    assert exc.session_id == "s1"
    assert exc.questions == ["Continue?"]
    assert exc.streamed_text == "partial"
    assert "Runtime asked a question" in str(exc)
