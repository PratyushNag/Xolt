# SPDX-License-Identifier: Apache-2.0

"""OpenCode runtime adapter exports."""

from xolt.runtimes.opencode.config import (
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
from xolt.runtimes.opencode.runtime import OpenCodeRuntime, OpenCodeRuntimeHandle
from xolt.runtimes.opencode.types import AgentConfig

__all__ = [
    "BACKEND_PORT",
    "DEFAULT_SKILLS",
    "MANAGE_SKILLS_SANDBOX_PATH",
    "PROXY_SCRIPT_SANDBOX_PATH",
    "PUBLIC_PORT",
    "RELOAD_FLAG_PATH",
    "AgentConfig",
    "OpenCodeRuntime",
    "OpenCodeRuntimeHandle",
    "build_opencode_config",
    "get_agent_manager_agent",
    "get_manage_skills_markdown",
    "get_proxy_script",
    "get_skill_finder_agent",
    "get_skills_from_env",
    "inject_env_var",
]
