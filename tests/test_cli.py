from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from xolt import BackendProvisionError
from xolt.cli import (
    add_agent,
    add_skills,
    attach_session,
    build_backend,
    build_parser,
    build_runtime,
    chat,
    clear_state,
    create_session,
    default_backend_name,
    default_runtime_name,
    doctor,
    get_state_file,
    list_agents,
    list_runtime_skills,
    load_state,
    main,
    reload_runtime,
    remove_agent,
    require_state,
    run_async,
    save_state,
    stop_session,
    with_saved_session,
)


def make_session() -> SimpleNamespace:
    return SimpleNamespace(
        backend=SimpleNamespace(sandbox_id="sandbox-123", owns_sandbox=True),
        session_id="session-123",
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
        send_message=AsyncMock(return_value="reply"),
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


def test_parser_accepts_planned_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["start"]).command == "start"
    assert parser.parse_args(["attach"]).command == "attach"
    assert parser.parse_args(["stop"]).command == "stop"
    assert parser.parse_args(["chat", "hello"]).command == "chat"
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
    state = load_state()
    assert state is not None
    assert state["sandbox_id"] == "sandbox-123"


@pytest.mark.asyncio
async def test_attach_and_stop_session_use_saved_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "state.json"))
    save_state(
        {
            "backend": "daytona",
            "runtime": "opencode",
            "sandbox_id": "sandbox-123",
            "session_id": "session-123",
            "cmd_id": "cmd-123",
        }
    )
    session = make_session()

    with patch("xolt.cli.XoltSession.attach", new_callable=AsyncMock, return_value=session):
        await attach_session(build_parser().parse_args(["attach"]))
        await stop_session(build_parser().parse_args(["stop"]))

    output = capsys.readouterr().out
    assert "Sandbox: sandbox-123" in output
    assert "Deleted sandbox sandbox-123" in output
    assert load_state() is None


@pytest.mark.asyncio
async def test_attach_and_stop_without_state_raise() -> None:
    with pytest.raises(SystemExit, match="No sandbox id provided"):
        await attach_session(build_parser().parse_args(["attach"]))
    with pytest.raises(SystemExit, match="No sandbox id provided"):
        await stop_session(build_parser().parse_args(["stop"]))


@pytest.mark.asyncio
async def test_with_saved_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "state.json"))
    save_state(
        {
            "backend": "daytona",
            "runtime": "opencode",
            "sandbox_id": "sandbox-123",
            "session_id": "session-123",
            "cmd_id": "cmd-123",
        }
    )
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
async def test_chat_prompt_and_interactive_paths(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    session = make_session()
    with patch("xolt.cli.with_saved_session", new_callable=AsyncMock, return_value=session):
        await chat(argparse.Namespace(prompt="hello", session_id="chat-1"))
    assert "reply" in capsys.readouterr().out

    session = make_session()
    inputs = iter(["", "hello", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with patch("xolt.cli.with_saved_session", new_callable=AsyncMock, return_value=session):
        await chat(argparse.Namespace(prompt=None, session_id="chat-1"))
    captured = capsys.readouterr()
    assert "Interactive chat. Type `exit` to quit." in captured.out
    assert "reply" in captured.out


def test_doctor_variants(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
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


@pytest.mark.asyncio
async def test_run_async_dispatches() -> None:
    for argv, target in [
        (["start"], "create_session"),
        (["attach", "sandbox-123"], "attach_session"),
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

    args = build_parser().parse_args(["doctor"])
    with patch("xolt.cli.doctor", return_value=0) as fn:
        assert await run_async(args) == 0
        fn.assert_called_once()


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
