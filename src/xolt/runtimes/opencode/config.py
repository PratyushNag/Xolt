# SPDX-License-Identifier: Apache-2.0

"""OpenCode runtime configuration helpers."""

from __future__ import annotations

import base64
import json
import logging
import os
from importlib import resources
from typing import Any

from xolt.runtimes.opencode.types import AgentConfig

logger = logging.getLogger(__name__)

PUBLIC_PORT = 3000
BACKEND_PORT = 3001
PROXY_SCRIPT_SANDBOX_PATH = "/home/daytona/opencode-proxy.js"
MANAGE_SKILLS_SANDBOX_DIR = "/home/daytona/.config/opencode/skills/manage-skills"
MANAGE_SKILLS_SANDBOX_PATH = f"{MANAGE_SKILLS_SANDBOX_DIR}/SKILL.md"
RELOAD_FLAG_PATH = "/tmp/.opencode-needs-reload"
DEFAULT_SKILLS: list[str] = []


def load_resource_text(name: str) -> str:
    """Read a bundled runtime resource."""

    return resources.files("xolt.runtimes.opencode.resources").joinpath(name).read_text()


def inject_env_var(name: str, content: str) -> str:
    """Generate a shell expression that sets a base64-decoded env var."""

    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"{name}=$(echo '{b64}' | base64 -d)"


def get_skills_from_env() -> list[str]:
    """Return startup skills from `XOLT_SKILLS` or defaults."""

    skills_env = os.environ.get("XOLT_SKILLS", "")
    if not skills_env:
        return list(DEFAULT_SKILLS)
    return [entry.strip() for entry in skills_env.split(",") if entry.strip()]


def get_proxy_script() -> str:
    """Return the bundled reverse proxy script."""

    return load_resource_text("opencode_proxy.js")


def get_manage_skills_markdown() -> str:
    """Return the bundled skill management skill definition."""

    return load_resource_text("manage_skills.md").format(
        reload_flag_path=RELOAD_FLAG_PATH
    )


def get_skill_finder_agent() -> AgentConfig:
    """Preset skill finder subagent."""

    return {
        "description": "Find and install OpenCode skills from the registry and GitHub",
        "mode": "subagent",
        "prompt": load_resource_text("skill_finder_prompt.md").format(
            reload_flag_path=RELOAD_FLAG_PATH
        ),
    }


def get_agent_manager_agent() -> AgentConfig:
    """Preset agent manager subagent."""

    return {
        "description": "Create and manage OpenCode subagents at runtime",
        "mode": "subagent",
        "prompt": load_resource_text("agent_manager_prompt.md").format(
            reload_flag_path=RELOAD_FLAG_PATH
        ),
    }


async def build_opencode_config(
    sandbox: Any,
    agents: dict[str, AgentConfig] | None = None,
) -> tuple[str, str]:
    """Build the OpenCode config payload for a sandbox."""

    preview_link = await sandbox.get_preview_link(1234)
    preview_url_pattern = str(preview_link.url).replace("1234", "{PORT}")

    system_prompt = " ".join(
        [
            "You are running in a Daytona sandbox.",
            "Use /home/daytona instead of /workspace for file operations.",
            f"Local services are exposed at: {preview_url_pattern}",
            "When starting a server, run it in the background and give the preview URL.",
            "You can search for and install new skills at runtime.",
            "To install a skill from any GitHub repo use: npx -y skills add <owner/repo> -a opencode -g -y",
            f"After changing skills or agents, signal a reload with: touch {RELOAD_FLAG_PATH}",
            "Do not call instance/dispose directly.",
        ]
    )

    agent_section: dict[str, dict[str, Any]] = {
        "daytona": {
            "description": "Daytona sandbox-aware coding agent",
            "mode": "primary",
            "prompt": system_prompt,
        }
    }

    if agents:
        for name, agent_cfg in agents.items():
            if name == "daytona":
                logger.warning("Cannot override the built-in 'daytona' agent.")
                continue
            agent_section[name] = dict(agent_cfg)

    opencode_config = {
        "$schema": "https://opencode.ai/config.json",
        "permission": "allow",
        "default_agent": "daytona",
        "agent": agent_section,
    }
    config_json = json.dumps(opencode_config)
    return inject_env_var("OPENCODE_CONFIG_CONTENT", config_json), config_json
