# SPDX-License-Identifier: Apache-2.0

"""OpenCode agent file helpers."""

from __future__ import annotations

import logging
from typing import Any

from xolt.exceptions import AgentError
from xolt.runtimes.opencode.types import AgentConfig

logger = logging.getLogger(__name__)

AGENTS_DIR = "/home/daytona/.config/opencode/agents"


def build_agent_markdown(name: str, config: AgentConfig) -> str:
    """Build a Markdown agent file from an agent config."""

    front_matter: list[str] = []
    for key in (
        "description",
        "mode",
        "model",
        "temperature",
        "steps",
        "top_p",
        "hidden",
        "disable",
        "color",
    ):
        if key not in config:
            continue
        value = config[key]
        if isinstance(value, bool):
            front_matter.append(f"{key}: {'true' if value else 'false'}")
        else:
            front_matter.append(f"{key}: {value}")

    tools = config.get("tools")
    if tools:
        front_matter.append("tools:")
        for tool_name, enabled in tools.items():
            front_matter.append(f"  {tool_name}: {'true' if enabled else 'false'}")

    body = config.get("prompt", "")
    header = "\n".join(front_matter)
    return f"---\n{header}\n---\n\n{body}\n"


async def deploy_agent(sandbox: Any, name: str, config: AgentConfig) -> None:
    """Deploy an agent markdown file into the sandbox."""

    agent_path = f"{AGENTS_DIR}/{name}.md"
    try:
        await sandbox.process.exec(f"mkdir -p {AGENTS_DIR}", timeout=5)
        await sandbox.fs.upload_file(build_agent_markdown(name, config).encode(), agent_path)
    except Exception as exc:
        raise AgentError(f"Failed to deploy agent '{name}': {exc}") from exc


async def remove_agent_file(sandbox: Any, name: str) -> None:
    """Remove an agent markdown file from the sandbox."""

    agent_path = f"{AGENTS_DIR}/{name}.md"
    try:
        result = await sandbox.process.exec(f"rm -f {agent_path}", timeout=5)
    except Exception as exc:
        raise AgentError(f"Failed to remove agent '{name}': {exc}") from exc
    if result.exit_code != 0:
        detail = result.result.strip() if result.result else "Unknown error"
        raise AgentError(f"Failed to remove agent '{name}': {detail}")


async def list_deployed_agents(sandbox: Any) -> list[str]:
    """List deployed agent names in the sandbox."""

    try:
        result = await sandbox.process.exec(
            f"find {AGENTS_DIR} -maxdepth 1 -name '*.md' -type f 2>/dev/null "
            "| xargs -I{} basename {} .md | sort -u",
            timeout=10,
        )
    except Exception:
        logger.warning("Sandbox unreachable while listing agents")
        return []
    if result.exit_code != 0 or not result.result:
        return []
    return [line.strip() for line in result.result.strip().splitlines() if line.strip()]
