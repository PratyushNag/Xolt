from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from xolt.cli import build_parser, create_session, doctor, get_state_file, load_state


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


def test_state_file_uses_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom-state.json"
    monkeypatch.setenv("XOLT_STATE_FILE", str(custom))
    assert get_state_file() == custom


@pytest.mark.asyncio
async def test_start_writes_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XOLT_STATE_FILE", str(tmp_path / "state.json"))
    parser = build_parser()
    args = parser.parse_args(["start"])

    session = SimpleNamespace(
        backend=SimpleNamespace(sandbox_id="sandbox-123"),
        session_id="session-123",
        cmd_id="cmd-123",
        preview_url=AsyncMock(return_value="https://preview.example.com"),
        close=AsyncMock(),
    )

    with patch("xolt.cli.build_backend", return_value=object()), patch(
        "xolt.cli.build_runtime",
        return_value=object(),
    ), patch("xolt.cli.XoltSession.create", new_callable=AsyncMock, return_value=session):
        await create_session(args)

    state = load_state()
    assert state is not None
    assert state["sandbox_id"] == "sandbox-123"


def test_doctor_fails_without_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.setenv("XOLT_BACKEND", "unknown")
    assert doctor() == 1


def test_doctor_passes_with_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    monkeypatch.setenv("XOLT_BACKEND", "daytona")
    monkeypatch.setenv("XOLT_RUNTIME", "opencode")
    with patch("xolt.cli.shutil.which", return_value="uv"):
        assert doctor() == 0
