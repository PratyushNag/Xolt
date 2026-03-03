from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from xolt.runtimes.opencode import (
    BACKEND_PORT,
    DEFAULT_SKILLS,
    MANAGE_SKILLS_SANDBOX_PATH,
    PROXY_SCRIPT_SANDBOX_PATH,
    PUBLIC_PORT,
    RELOAD_FLAG_PATH,
    build_opencode_config,
    get_agent_manager_agent,
    get_manage_skills_markdown,
    get_proxy_script,
    get_skill_finder_agent,
    get_skills_from_env,
    inject_env_var,
)


def test_constants_are_sane() -> None:
    assert PUBLIC_PORT != BACKEND_PORT
    assert PROXY_SCRIPT_SANDBOX_PATH.startswith("/")
    assert MANAGE_SKILLS_SANDBOX_PATH.startswith("/")
    assert RELOAD_FLAG_PATH.startswith("/")
    assert isinstance(DEFAULT_SKILLS, list)


def test_inject_env_var() -> None:
    command = inject_env_var("XOLT", '{"key":"value"}')
    assert command.startswith("XOLT=")
    assert "base64" in command


def test_get_skills_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XOLT_SKILLS", "a/b, c/d")
    assert get_skills_from_env() == ["a/b", "c/d"]


def test_get_skills_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XOLT_SKILLS", raising=False)
    assert get_skills_from_env() == list(DEFAULT_SKILLS)


def test_resource_helpers_return_content() -> None:
    assert "http" in get_proxy_script().lower()
    assert "manage-skills" in get_manage_skills_markdown()
    assert RELOAD_FLAG_PATH in get_skill_finder_agent()["prompt"]
    assert RELOAD_FLAG_PATH in get_agent_manager_agent()["prompt"]


@pytest.mark.asyncio
async def test_build_opencode_config_merges_custom_agents() -> None:
    sandbox = MagicMock()
    sandbox.get_preview_link = AsyncMock(
        return_value=SimpleNamespace(url="https://preview.example.com:1234")
    )
    _, config_json = await build_opencode_config(
        sandbox,
        agents={
            "reviewer": {
                "description": "Code reviewer",
                "mode": "subagent",
                "prompt": "Review code.",
            }
        },
    )
    config = json.loads(config_json)
    assert config["default_agent"] == "daytona"
    assert config["agent"]["reviewer"]["description"] == "Code reviewer"
    assert "Daytona sandbox" in config["agent"]["daytona"]["prompt"]
