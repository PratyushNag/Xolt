# SPDX-License-Identifier: Apache-2.0

"""OpenCode skill operations."""

from __future__ import annotations

import json
import logging
from typing import Any

from xolt.exceptions import RuntimeReloadError, SkillInstallError
from xolt.runtimes.opencode.config import BACKEND_PORT

logger = logging.getLogger(__name__)


async def install_skills(
    sandbox: Any,
    skills: list[str],
    *,
    timeout: int = 120,
) -> tuple[list[str], list[str]]:
    """Install one or more skills into a sandbox."""

    installed: list[str] = []
    failed: list[str] = []
    for skill_source in skills:
        name = skill_source.strip()
        if not name:
            continue
        try:
            result = await sandbox.process.exec(
                f"npx -y skills add {name} -a opencode -g -y",
                timeout=timeout,
            )
        except Exception as exc:
            raise SkillInstallError(
                f"Sandbox unreachable while installing skill '{name}': {exc}"
            ) from exc
        if result.exit_code == 0:
            installed.append(name)
        else:
            failed.append(name)
    return installed, failed


async def list_skills(sandbox: Any) -> list[str]:
    """List installed skill directories in the sandbox."""

    try:
        result = await sandbox.process.exec(
            "find ~/.agents/skills ~/.config/opencode/skills ~/.claude/skills "
            "-maxdepth 1 -mindepth 1 -type d 2>/dev/null "
            "| xargs -I{} basename {} | sort -u",
            timeout=10,
        )
    except Exception:
        logger.warning("Sandbox unreachable while listing skills")
        return []
    if result.exit_code != 0 or not result.result:
        return []
    return [line.strip() for line in result.result.strip().splitlines() if line.strip()]


async def dispose_all_instances(sandbox: Any) -> None:
    """Dispose OpenCode instance caches for the default and active directories."""

    directories: set[str] = set()
    try:
        response = await sandbox.process.exec(
            f"curl -s http://localhost:{BACKEND_PORT}/session",
            timeout=5,
        )
        if response.exit_code == 0 and response.result:
            sessions = json.loads(response.result)
            for session in sessions:
                directory = session.get("directory")
                if isinstance(directory, str) and directory:
                    directories.add(directory)
    except Exception:
        logger.debug("Failed to query active OpenCode sessions")

    try:
        result = await sandbox.process.exec(
            f"curl -s -X POST http://localhost:{BACKEND_PORT}/instance/dispose",
            timeout=10,
        )
    except Exception as exc:
        raise RuntimeReloadError(f"Sandbox unreachable while reloading runtime: {exc}") from exc

    if result.exit_code != 0:
        detail = result.result.strip() if result.result else "Unknown error"
        logger.warning("Default instance dispose may have failed: %s", detail)

    for directory in directories:
        try:
            await sandbox.process.exec(
                f'curl -s -X POST "http://localhost:{BACKEND_PORT}/instance/dispose?directory={directory}"',
                timeout=10,
            )
        except Exception:
            logger.warning("Failed to dispose instance for directory: %s", directory)
