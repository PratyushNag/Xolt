# SPDX-License-Identifier: Apache-2.0

"""Tasking types for streamed SDK workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

TaskStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "blocked",
]


@dataclass(frozen=True)
class TaskHandle:
    """A submitted task bound to a runtime chat session."""

    id: str
    chat_session_id: str
    prompt: str
    created_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    """Final result for a submitted task."""

    task_id: str
    chat_session_id: str
    status: TaskStatus
    response: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class TaskEvent:
    """Structured event emitted while a task is running."""

    id: str
    type: str
    ts: datetime
    worker_id: str
    chat_session_id: str
    task_id: str
    sequence: int
    payload: dict[str, Any]
