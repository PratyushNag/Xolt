from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from xolt import (
    BackendProvisionError,
    QuestionAskedError,
    TaskBlocker,
    TaskEvent,
    TaskHandle,
    TaskResult,
)
from xolt.cli import (
    add_agent,
    add_skills,
    build_backend,
    build_parser,
    build_runtime,
    chat,
    clear_state,
    companion_session,
    console_session,
    create_session,
    default_backend_name,
    default_runtime_name,
    doctor,
    get_state_file,
    list_agents,
    list_runtime_skills,
    load_state,
    main,
    open_runtime,
    reload_runtime,
    remove_agent,
    require_state,
    run_async,
    save_state,
    status_session,
    stop_session,
    with_saved_session,
)


async def _iter_task_events(events: list[TaskEvent]):
    for event in events:
        yield event


def make_session() -> SimpleNamespace:
    return SimpleNamespace(
        backend=SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True),
        session_id="runtime-session-123",
        cmd_id="cmd-123",
        preview_url=AsyncMock(return_value="https://preview.example.com"),
        close=AsyncMock(),
        delete=AsyncMock(),
        add_skills=AsyncMock(return_value=(["a/b"], ["bad/repo"])),
        list_skills=AsyncMock(return_value=["browser-use"]),
        reload_runtime=AsyncMock(),
        add_agent=AsyncMock(),
        list_agents=AsyncMock(return_value=["reviewer"]),
        remove_agent=AsyncMock(),
        create_chat_session=AsyncMock(return_value={"id": "chat-123"}),
        send_message=AsyncMock(return_value="reply"),
        list_files=AsyncMock(return_value=[{"path": "src", "type": "directory"}]),
        get_file_tree=AsyncMock(
            return_value=[{"path": "src", "type": "directory", "children": []}]
        ),
        get_session_diff=AsyncMock(return_value=[{"path": "README.md", "op": "edit"}]),
    )


def write_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "state.json"))
    save_state(
        {
            "backend": "daytona",
            "runtime": "opencode",
            "sandbox_id": "sandbox-123",
            "session_id": "runtime-session-123",
            "cmd_id": "cmd-123",
        }
    )


def test_default_backend_and_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XOLT_BACKEND", "daytona")
    monkeypatch.setenv("XOLT_RUNTIME", "opencode")
    assert default_backend_name() == "daytona"
    assert default_runtime_name() == "opencode"


def test_state_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "custom-state.json"))
    state_file = get_state_file()
    assert state_file == tmp_path / "custom-state.json"
    save_state({"sandbox_id": "sandbox-123"})
    assert load_state() == {"sandbox_id": "sandbox-123"}
    assert require_state() == {"sandbox_id": "sandbox-123"}
    clear_state()
    assert load_state() is None
    with pytest.raises(SystemExit, match="No active Xolt session found"):
        require_state()


def test_build_backend_and_runtime_errors() -> None:
    with pytest.raises(SystemExit, match="Unsupported backend"):
        build_backend("docker")
    with pytest.raises(SystemExit, match="Unsupported runtime"):
        build_runtime("claude")


def test_build_backend_and_runtime_success() -> None:
    backend = build_backend("daytona")
    runtime = build_runtime("opencode", skills=["a/b"])
    assert backend.name == "daytona"
    assert runtime.name == "opencode"


def test_parser_accepts_new_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["start"]).command == "start"
    assert parser.parse_args(["attach", "--raw-event"]).raw_event is True
    assert parser.parse_args(["attach"]).command == "attach"
    assert parser.parse_args(["console", "--raw-event"]).raw_event is True
    assert parser.parse_args(["console"]).command == "console"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["open"]).command == "open"
    assert parser.parse_args(["stop"]).command == "stop"
    assert parser.parse_args(["chat", "hello"]).command == "chat"
    assert parser.parse_args(["chat", "--interactive"]).interactive is True
    assert parser.parse_args(["chat", "hello", "--raw-event"]).raw_event is True
    assert parser.parse_args(["companion", "--raw-events"]).raw_event is True
    assert parser.parse_args(["companion", "--timeout", "42"]).timeout == 42.0
    assert parser.parse_args(["skills", "add", "a/b"]).skills_command == "add"
    assert parser.parse_args(["runtime", "reload"]).runtime_command == "reload"
    assert parser.parse_args(["agents", "list"]).agents_command == "list"
    assert parser.parse_args(["doctor"]).command == "doctor"


@pytest.mark.asyncio
async def test_start_writes_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "state.json"))
    args = build_parser().parse_args(["start", "--skill", "a/b"])
    session = make_session()

    with (
        patch("xolt.cli.build_backend", return_value=object()),
        patch("xolt.cli.build_runtime", return_value=object()),
        patch("xolt.cli.XoltSession.create", new_callable=AsyncMock, return_value=session),
    ):
        await create_session(args)

    captured = capsys.readouterr()
    assert "preview.example.com" in captured.out
    assert "xolt attach" in captured.out
    state = load_state()
    assert state is not None
    assert state["sandbox_id"] == "sandbox-123"


@pytest.mark.asyncio
async def test_status_open_console_and_stop_use_saved_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    inputs = iter(["/status", "/skills", "/agents", "/open", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("xolt.cli.XoltSession.attach", new_callable=AsyncMock, return_value=session):
        await status_session(build_parser().parse_args(["status"]))
        await open_runtime(build_parser().parse_args(["open"]))
        await console_session(build_parser().parse_args(["attach"]))
        await stop_session(build_parser().parse_args(["stop"]))

    output = capsys.readouterr().out
    assert "Reachable: yes" in output
    assert "Preview URL: https://preview.example.com" in output
    assert "Attached to sandbox sandbox-123" in output
    assert "Operator console ready." in output
    assert "browser-use" in output
    assert "reviewer" in output
    assert "Deleted sandbox sandbox-123" in output
    assert load_state() is None


@pytest.mark.asyncio
async def test_status_console_and_stop_without_state_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "state.json"))
    clear_state()
    with pytest.raises(SystemExit, match="No sandbox id provided"):
        await status_session(build_parser().parse_args(["status"]))
    with pytest.raises(SystemExit, match="No sandbox id provided"):
        await console_session(build_parser().parse_args(["attach"]))
    with pytest.raises(SystemExit, match="No sandbox id provided"):
        await stop_session(build_parser().parse_args(["stop"]))


@pytest.mark.asyncio
async def test_with_saved_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    with patch("xolt.cli.XoltSession.attach", new_callable=AsyncMock, return_value=session):
        attached = await with_saved_session()
    assert attached is session


@pytest.mark.asyncio
async def test_skill_agent_and_reload_commands(capsys) -> None:
    session = make_session()
    args = argparse.Namespace(sources=["a/b"], no_reload=False)
    with patch("xolt.cli.with_saved_session", new_callable=AsyncMock, return_value=session):
        await add_skills(args)
        await list_runtime_skills()
        await reload_runtime()

    prompt_path = Path("temp-agent.md")
    prompt_path.write_text("Prompt", encoding="utf-8")
    try:
        add_args = argparse.Namespace(
            name="reviewer",
            path=str(prompt_path),
            description="Reviewer",
            no_reload=True,
        )
        remove_args = argparse.Namespace(name="reviewer", no_reload=False)
        with patch("xolt.cli.with_saved_session", new_callable=AsyncMock, return_value=session):
            await add_agent(add_args)
            await list_agents()
            await remove_agent(remove_args)
    finally:
        prompt_path.unlink(missing_ok=True)

    output = capsys.readouterr()
    assert "Installed: a/b" in output.out
    assert "browser-use" in output.out
    assert "Runtime reloaded" in output.out
    assert "Added agent reviewer" in output.out
    assert "Removed agent reviewer" in output.out
    assert "bad/repo" in output.err


@pytest.mark.asyncio
async def test_chat_prompt_and_interactive_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    with patch("xolt.cli.with_saved_session", new_callable=AsyncMock, return_value=session):
        await chat(
            argparse.Namespace(prompt="hello", session_id=None, interactive=False, raw_event=False)
        )

    assert "reply" in capsys.readouterr().out
    state = load_state()
    assert state is not None
    assert state["chat_session_id"] == "chat-123"
    session.send_message.assert_awaited_once_with(
        "hello",
        session_id="chat-123",
        on_event=None,
    )

    session = make_session()
    save_state(
        {
            "backend": "daytona",
            "runtime": "opencode",
            "sandbox_id": "sandbox-123",
            "session_id": "runtime-session-123",
            "cmd_id": "cmd-123",
            "chat_session_id": "chat-123",
        }
    )
    inputs = iter(["hello", "/files src", "/tree src", "/diff", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with patch("xolt.cli._attach_resolved_session", new_callable=AsyncMock, return_value=session):
        await chat(
            argparse.Namespace(prompt=None, session_id=None, interactive=True, raw_event=False)
        )

    captured = capsys.readouterr()
    assert "Operator console ready." in captured.out
    assert "reply" in captured.out
    assert "directory: src" in captured.out
    assert "edit: README.md" in captured.out


@pytest.mark.asyncio
async def test_chat_raw_events_enable_event_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    with patch("xolt.cli.XoltSession.attach", new_callable=AsyncMock, return_value=session):
        await chat(build_parser().parse_args(["chat", "hello", "--raw-event"]))
    called_kwargs = session.send_message.await_args.kwargs
    assert called_kwargs["on_event"] is not None


@pytest.mark.asyncio
async def test_console_raw_events_enable_event_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    inputs = iter(["hello", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("xolt.cli.XoltSession.attach", new_callable=AsyncMock, return_value=session):
        await console_session(build_parser().parse_args(["attach", "--raw-event"]))

    called_kwargs = session.send_message.await_args.kwargs
    assert called_kwargs["on_event"] is not None


@pytest.mark.asyncio
async def test_console_handles_chat_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    session.send_message = AsyncMock(
        side_effect=QuestionAskedError("q1", "chat-123", ["Continue?"])
    )
    inputs = iter(["hello", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("xolt.cli.XoltSession.attach", new_callable=AsyncMock, return_value=session):
        await console_session(build_parser().parse_args(["attach"]))

    assert "Runtime asked a question" in capsys.readouterr().err


def test_doctor_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.setenv("XOLT_BACKEND", "unknown")
    monkeypatch.setenv("XOLT_RUNTIME", "bad")
    with patch("xolt.cli.shutil.which", return_value=None):
        assert doctor() == 1
    err = capsys.readouterr().err
    assert "uv is not installed" in err
    assert "Unsupported backend" in err
    assert "DAYTONA_API_KEY is not set." in err

    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    monkeypatch.setenv("XOLT_BACKEND", "daytona")
    monkeypatch.setenv("XOLT_RUNTIME", "opencode")
    with patch("xolt.cli.shutil.which", return_value="uv"):
        assert doctor() == 0


def test_doctor_loads_dotenv_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.delenv("XOLT_BACKEND", raising=False)
    monkeypatch.delenv("XOLT_RUNTIME", raising=False)
    (tmp_path / ".env").write_text("DAYTONA_API_KEY=test-key\n", encoding="utf-8")

    with patch("xolt.cli.shutil.which", return_value="uv"):
        assert doctor() == 0

    assert "Xolt doctor checks passed." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_async_dispatches() -> None:
    for argv, target in [
        (["start"], "create_session"),
        (["attach", "sandbox-123"], "console_session"),
        (["console", "sandbox-123"], "console_session"),
        (["status", "sandbox-123"], "status_session"),
        (["open"], "open_runtime"),
        (["stop", "sandbox-123"], "stop_session"),
        (["chat", "hello"], "chat"),
        (["skills", "add", "a/b"], "add_skills"),
        (["skills", "list"], "list_runtime_skills"),
        (["runtime", "reload"], "reload_runtime"),
        (["agents", "list"], "list_agents"),
        (["agents", "remove", "reviewer"], "remove_agent"),
    ]:
        args = build_parser().parse_args(argv)
        with patch(f"xolt.cli.{target}", new_callable=AsyncMock) as fn:
            assert await run_async(args) == 0
            fn.assert_awaited_once()

    args = build_parser().parse_args(["agents", "add", "reviewer", "prompt.md"])
    with patch("xolt.cli.add_agent", new_callable=AsyncMock) as fn:
        assert await run_async(args) == 0
        fn.assert_awaited_once()

    args = build_parser().parse_args(["companion"])
    with patch("xolt.cli.companion_session", new_callable=AsyncMock) as fn:
        assert await run_async(args) == 0
        fn.assert_awaited_once()

    args = build_parser().parse_args(["doctor"])
    with patch("xolt.cli.doctor", return_value=0) as fn:
        assert await run_async(args) == 0
        fn.assert_called_once()


@pytest.mark.asyncio
async def test_companion_session_submits_and_streams_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    task = TaskHandle(
        id="task-1",
        chat_session_id="chat-123",
        prompt="Inspect files",
        created_at=datetime(2026, 1, 1),
    )

    async def _stream() -> None:
        async for event in _iter_task_events(
            [
                TaskEvent(
                    id="event-1",
                    type="message_delta",
                    ts=datetime(2026, 1, 1),
                    worker_id="worker",
                    chat_session_id="chat-123",
                    task_id="task-1",
                    sequence=1,
                    payload={"delta": "hello"},
                ),
                TaskEvent(
                    id="event-2",
                    type="status",
                    ts=datetime(2026, 1, 1),
                    worker_id="worker",
                    chat_session_id="chat-123",
                    task_id="task-1",
                    sequence=2,
                    payload={"status": "idle"},
                ),
            ]
        ):
            yield event

    session.submit_task = AsyncMock(return_value=task)
    session.stream_task = lambda *_args, **_kwargs: _stream()
    session.wait_task = AsyncMock(
        return_value=TaskResult(
            task_id="task-1",
            chat_session_id="chat-123",
            status="completed",
            response="done",
        )
    )
    inputs = iter(["Inspect workspace", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("xolt.cli._attach_resolved_session", new_callable=AsyncMock, return_value=session):
        await companion_session(build_parser().parse_args(["companion"]))

    output = capsys.readouterr().out
    assert "task.started: task-1" in output
    assert "task.completed: task-1" in output
    assert "status: completed" in output


@pytest.mark.asyncio
async def test_companion_session_handles_blocked_task_and_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    write_state(monkeypatch, tmp_path)
    session = make_session()
    task = TaskHandle(
        id="task-2",
        chat_session_id="chat-123",
        prompt="Need clarification",
        created_at=datetime(2026, 1, 2),
    )
    session.submit_task = AsyncMock(return_value=task)
    session.stream_task = lambda *_args, **_kwargs: _iter_task_events([])
    session.wait_task = AsyncMock(
        side_effect=[
            TaskResult(
                task_id="task-2",
                chat_session_id="chat-123",
                status="blocked",
                response=None,
                error=None,
            ),
            TaskResult(
                task_id="task-2",
                chat_session_id="chat-123",
                status="blocked",
                response=None,
                error=None,
            ),
            TaskResult(
                task_id="task-2",
                chat_session_id="chat-123",
                status="completed",
                response="all good",
                error=None,
            ),
        ]
    )
    session.get_task_blocker = lambda *_args, **_kwargs: TaskBlocker(
        task_id="task-2",
        chat_session_id="chat-123",
        question_id="q1",
        questions=["What is the priority?"],
        streamed_text="",
        payload={},
        seen_at=datetime(2026, 1, 2),
    )
    session.resume_blocked_task = AsyncMock(return_value=task)

    inputs = iter(["Need clarification", "high", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("xolt.cli._attach_resolved_session", new_callable=AsyncMock, return_value=session):
        await companion_session(build_parser().parse_args(["companion"]))

    captured = capsys.readouterr().out
    assert "Task blocked. Runtime asked:" in captured
    assert "1. What is the priority?" in captured
    assert "task.completed: task-2" in captured


def test_main_success_and_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(command="doctor")
    monkeypatch.setattr("xolt.cli.build_parser", lambda: SimpleNamespace(parse_args=lambda: args))

    def successful_run(coro: object) -> int:
        coro.close()
        return 0

    monkeypatch.setattr("xolt.cli.asyncio.run", successful_run)
    with pytest.raises(SystemExit, match="0"):
        main()

    def failing_run(coro: object) -> int:
        coro.close()
        raise BackendProvisionError("bad backend")

    monkeypatch.setattr("xolt.cli.asyncio.run", failing_run)
    with pytest.raises(SystemExit, match="1"):
        main()
