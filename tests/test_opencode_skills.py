from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from xolt.exceptions import RuntimeReloadError, SkillInstallError
from xolt.runtimes.opencode.skills import dispose_all_instances, install_skills, list_skills


@pytest.mark.asyncio
async def test_install_skills_success_and_failures() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(
        side_effect=[
            SimpleNamespace(exit_code=0, result="ok"),
            SimpleNamespace(exit_code=1, result="bad"),
        ]
    )
    installed, failed = await install_skills(sandbox, ["a/b", " c/d "])
    assert installed == ["a/b"]
    assert failed == ["c/d"]


@pytest.mark.asyncio
async def test_install_skills_skips_blanks_and_wraps_errors() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(return_value=SimpleNamespace(exit_code=0, result="ok"))
    installed, failed = await install_skills(sandbox, ["", "  "])
    assert installed == []
    assert failed == []

    sandbox.process.exec = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(SkillInstallError, match="Sandbox unreachable while installing skill 'a/b'"):
        await install_skills(sandbox, ["a/b"])


@pytest.mark.asyncio
async def test_list_skills_paths() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(
        return_value=SimpleNamespace(exit_code=0, result="browser-use\nremote-browser")
    )
    assert await list_skills(sandbox) == ["browser-use", "remote-browser"]

    sandbox.process.exec = AsyncMock(return_value=SimpleNamespace(exit_code=1, result=""))
    assert await list_skills(sandbox) == []

    sandbox.process.exec = AsyncMock(side_effect=RuntimeError("boom"))
    assert await list_skills(sandbox) == []


@pytest.mark.asyncio
async def test_dispose_all_instances_success_and_errors() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(
        side_effect=[
            SimpleNamespace(
                exit_code=0,
                result=json.dumps([{"directory": "/root"}, {"directory": "/workspace"}]),
            ),
            SimpleNamespace(exit_code=0, result="ok"),
            SimpleNamespace(exit_code=0, result="ok"),
            SimpleNamespace(exit_code=0, result="ok"),
        ]
    )
    await dispose_all_instances(sandbox)
    assert sandbox.process.exec.await_count == 4

    sandbox.process.exec = AsyncMock(
        side_effect=[
            RuntimeError("session lookup failed"),
            SimpleNamespace(exit_code=0, result="ok"),
        ]
    )
    await dispose_all_instances(sandbox)

    sandbox.process.exec = AsyncMock(side_effect=RuntimeError("dispose failed"))
    with pytest.raises(RuntimeReloadError, match="Sandbox unreachable while reloading runtime"):
        await dispose_all_instances(sandbox)


@pytest.mark.asyncio
async def test_dispose_all_instances_handles_nonzero_and_directory_failures() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(
        side_effect=[
            SimpleNamespace(exit_code=0, result=json.dumps([{"directory": "/workspace"}])),
            SimpleNamespace(exit_code=1, result="bad"),
            RuntimeError("directory dispose failed"),
        ]
    )
    await dispose_all_instances(sandbox)
