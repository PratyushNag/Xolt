# SPDX-License-Identifier: Apache-2.0

"""Public OpenCode runtime types."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentConfig(TypedDict, total=False):
    """Configuration for an OpenCode agent."""

    description: str
    mode: str
    model: str
    prompt: str
    temperature: float
    steps: int
    tools: dict[str, bool]
    permission: dict[str, Any]
    hidden: bool
    color: str
    top_p: float
    disable: bool
