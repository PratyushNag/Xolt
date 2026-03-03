from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xolt.backends.base import PreviewAccess  # noqa: E402


class DummyBackendHandle:
    def __init__(self, sandbox: MagicMock, *, owns_sandbox: bool = True) -> None:
        self.sandbox = sandbox
        self.sandbox_id = str(sandbox.id)
        self.owns_sandbox = owns_sandbox
        self.delete = AsyncMock()
        self.close = AsyncMock()
        self.get_preview_access = AsyncMock(
            return_value=PreviewAccess(
                url="https://preview.example.com",
                token="preview-token",
            )
        )


@pytest.fixture()
def mock_sandbox() -> MagicMock:
    sandbox = MagicMock()
    sandbox.id = "sandbox-123"

    exec_result = SimpleNamespace(exit_code=0, result="")
    sandbox.process.exec = AsyncMock(return_value=exec_result)
    sandbox.process.create_session = AsyncMock()
    sandbox.process.execute_session_command = AsyncMock(
        return_value=SimpleNamespace(cmd_id="cmd-123")
    )
    sandbox.fs.upload_file = AsyncMock()
    sandbox.get_preview_link = AsyncMock(
        return_value=SimpleNamespace(
            url="https://preview.example.com",
            token="preview-token",
        )
    )
    return sandbox


@pytest.fixture()
def backend_handle(mock_sandbox: MagicMock) -> DummyBackendHandle:
    return DummyBackendHandle(mock_sandbox)


@pytest.fixture()
def attached_backend_handle(mock_sandbox: MagicMock) -> DummyBackendHandle:
    return DummyBackendHandle(mock_sandbox, owns_sandbox=False)
