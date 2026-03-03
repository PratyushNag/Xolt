from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from xolt.exceptions import FileError, MessageError, QuestionAskedError
from xolt.runtimes.opencode.runtime import OpenCodeRuntime, OpenCodeRuntimeHandle
from xolt.session import XoltSession


@pytest.fixture()
def runtime_handle(backend_handle) -> OpenCodeRuntimeHandle:
    return OpenCodeRuntimeHandle(
        backend_handle,
        session_id="session-123",
        cmd_id="cmd-123",
    )


@pytest.mark.asyncio
async def test_session_create_delegates(mock_sandbox) -> None:
    backend = SimpleNamespace(create=AsyncMock(), attach=AsyncMock())
    runtime = SimpleNamespace(start=AsyncMock(), attach=AsyncMock())
    backend_handle = SimpleNamespace(owns_sandbox=True)
    runtime_handle = SimpleNamespace(
        session_id="s1",
        cmd_id="c1",
        installed_skills=[],
        deployed_agents=[],
    )
    backend.create.return_value = backend_handle
    runtime.start.return_value = runtime_handle

    session = await XoltSession.create(backend=backend, runtime=runtime)
    assert session.session_id == "s1"
    backend.create.assert_awaited_once()
    runtime.start.assert_awaited_once_with(backend_handle)


@pytest.mark.asyncio
async def test_preview_url_and_close_delegate(runtime_handle, backend_handle) -> None:
    assert await runtime_handle.preview_url() == "https://preview.example.com"
    await runtime_handle.close()
    backend_handle.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_skills_updates_tracked_state(runtime_handle) -> None:
    with (
        patch(
            "xolt.runtimes.opencode.runtime.install_skills",
            new_callable=AsyncMock,
            return_value=(["a/b"], []),
        ),
        patch(
            "xolt.runtimes.opencode.runtime.dispose_all_instances",
            new_callable=AsyncMock,
        ) as dispose,
    ):
        installed, failed = await runtime_handle.add_skills(["a/b"])
    assert installed == ["a/b"]
    assert failed == []
    assert runtime_handle.installed_skills == ["a/b"]
    dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_management_updates_tracked_state(runtime_handle) -> None:
    with (
        patch(
            "xolt.runtimes.opencode.runtime.deploy_agent",
            new_callable=AsyncMock,
        ),
        patch(
            "xolt.runtimes.opencode.runtime.dispose_all_instances",
            new_callable=AsyncMock,
        ),
    ):
        await runtime_handle.add_agent("reviewer", {"description": "Code reviewer"})
    assert runtime_handle.deployed_agents == ["reviewer"]

    with (
        patch(
            "xolt.runtimes.opencode.runtime.remove_agent_file",
            new_callable=AsyncMock,
        ),
        patch(
            "xolt.runtimes.opencode.runtime.dispose_all_instances",
            new_callable=AsyncMock,
        ),
    ):
        await runtime_handle.remove_agent("reviewer")
    assert runtime_handle.deployed_agents == []


@pytest.mark.asyncio
async def test_send_message_uses_streamed_text_fallback(runtime_handle) -> None:
    client = AsyncMock()
    client.send_message_async = AsyncMock()
    client.list_messages = AsyncMock(return_value=[{"info": {"role": "assistant"}, "parts": []}])
    runtime_handle._client = client
    runtime_handle._wait_for_idle = AsyncMock(return_value="streamed text")  # type: ignore[method-assign]
    runtime_handle._check_and_dispose = AsyncMock(return_value=False)  # type: ignore[method-assign]
    assert await runtime_handle.send_message("hello", session_id="s1") == "streamed text"


@pytest.mark.asyncio
async def test_send_message_raises_agent_errors(runtime_handle) -> None:
    client = AsyncMock()
    client.send_message_async = AsyncMock()
    client.list_messages = AsyncMock(
        return_value=[
            {
                "info": {"role": "assistant", "error": {"message": "bad"}},
                "parts": [],
            }
        ]
    )
    runtime_handle._client = client
    runtime_handle._wait_for_idle = AsyncMock(return_value="")  # type: ignore[method-assign]
    runtime_handle._check_and_dispose = AsyncMock(return_value=False)  # type: ignore[method-assign]
    with pytest.raises(MessageError, match="Agent error"):
        await runtime_handle.send_message("hello", session_id="s1")


@pytest.mark.asyncio
async def test_wait_for_idle_raises_question_error(runtime_handle) -> None:
    async def stream():
        yield {
            "type": "question.asked",
            "properties": {"id": "q1", "sessionID": "s1", "questions": ["Continue?"]},
        }

    runtime_handle.stream_events = stream  # type: ignore[method-assign]
    with pytest.raises(QuestionAskedError):
        await runtime_handle._wait_for_idle()


@pytest.mark.asyncio
async def test_get_file_tree_recurses(runtime_handle) -> None:
    client = AsyncMock()
    client.list_files = AsyncMock(
        side_effect=[
            [
                {"name": "src", "path": "/root/src", "type": "directory"},
                {"name": "main.py", "path": "/root/main.py", "type": "file"},
            ],
            [{"name": "app.py", "path": "/root/src/app.py", "type": "file"}],
        ]
    )
    runtime_handle._client = client
    tree = await runtime_handle.get_file_tree("/root", max_depth=2)
    assert tree[0]["children"][0]["name"] == "app.py"


@pytest.mark.asyncio
async def test_get_session_diff_requires_session_id(runtime_handle) -> None:
    with pytest.raises(FileError, match="session_id is required"):
        await runtime_handle.get_session_diff()


def test_extract_and_classify_helpers() -> None:
    assert (
        OpenCodeRuntimeHandle.extract_text({"parts": [{"type": "text", "text": "hello"}]})
        == "hello"
    )
    assert OpenCodeRuntimeHandle.extract_response([]) == "(no response)"
    assert OpenCodeRuntimeHandle.classify_file_event(
        {"type": "session.status", "properties": {"status": "idle"}}
    ) == {"op": "reconcile"}


@pytest.mark.asyncio
async def test_runtime_start_bootstraps_sandbox(mock_sandbox, backend_handle) -> None:
    runtime = OpenCodeRuntime(skills=["a/b"])
    with (
        patch(
            "xolt.runtimes.opencode.runtime.install_skills",
            new_callable=AsyncMock,
            return_value=(["a/b"], []),
        ),
        patch(
            "xolt.runtimes.opencode.runtime.build_opencode_config",
            new_callable=AsyncMock,
            return_value=("ENV=1", "{}"),
        ),
        patch(
            "xolt.runtimes.opencode.runtime.get_proxy_script",
            return_value="// proxy",
        ),
        patch.dict(
            sys.modules,
            {
                "daytona": SimpleNamespace(
                    SessionExecuteRequest=lambda **kwargs: SimpleNamespace(**kwargs)
                )
            },
        ),
    ):
        handle = await runtime.start(backend_handle)
    assert handle.session_id.startswith("xolt-runtime-")
    mock_sandbox.fs.upload_file.assert_awaited()
