from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from xolt.exceptions import AgentError
from xolt.runtimes.opencode.agents import (
    build_agent_markdown,
    deploy_agent,
    list_deployed_agents,
    remove_agent_file,
)


def test_build_agent_markdown() -> None:
    markdown = build_agent_markdown(
        "reviewer",
        {
            "description": "Code reviewer",
            "mode": "subagent",
            "hidden": True,
            "tools": {"bash": True, "web": False},
            "prompt": "Review code",
        },
    )
    assert "description: Code reviewer" in markdown
    assert "hidden: true" in markdown
    assert "bash: true" in markdown
    assert "Review code" in markdown


@pytest.mark.asyncio
async def test_deploy_agent_success() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock()
    sandbox.fs.upload_file = AsyncMock()
    await deploy_agent(sandbox, "reviewer", {"description": "Code reviewer"})
    sandbox.process.exec.assert_awaited_once()
    sandbox.fs.upload_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_deploy_agent_wraps_errors() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(side_effect=RuntimeError("boom"))
    sandbox.fs.upload_file = AsyncMock()
    with pytest.raises(AgentError, match="Failed to deploy agent 'reviewer'"):
        await deploy_agent(sandbox, "reviewer", {"description": "Code reviewer"})


@pytest.mark.asyncio
async def test_remove_agent_file_paths() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(return_value=SimpleNamespace(exit_code=0, result=""))
    await remove_agent_file(sandbox, "reviewer")

    sandbox.process.exec = AsyncMock(return_value=SimpleNamespace(exit_code=1, result="failed"))
    with pytest.raises(AgentError, match="failed"):
        await remove_agent_file(sandbox, "reviewer")

    sandbox.process.exec = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(AgentError, match="Failed to remove agent 'reviewer'"):
        await remove_agent_file(sandbox, "reviewer")


@pytest.mark.asyncio
async def test_list_deployed_agents_paths() -> None:
    sandbox = MagicMock()
    sandbox.process.exec = AsyncMock(return_value=SimpleNamespace(exit_code=0, result="reviewer\nresearcher"))
    assert await list_deployed_agents(sandbox) == ["reviewer", "researcher"]

    sandbox.process.exec = AsyncMock(return_value=SimpleNamespace(exit_code=0, result=""))
    assert await list_deployed_agents(sandbox) == []

    sandbox.process.exec = AsyncMock(side_effect=RuntimeError("boom"))
    assert await list_deployed_agents(sandbox) == []
