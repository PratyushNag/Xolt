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
ArtifactKind = Literal["messages", "diff", "file_changes", "response", "blocker"]


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


@dataclass(frozen=True)
class TaskFileChange:
    """A normalized file change discovered while a task was running."""

    task_id: str
    chat_session_id: str
    path: str
    operation: str
    sequence: int
    ts: datetime


@dataclass(frozen=True)
class TaskDiffEntry:
    """A normalized diff entry for a completed or in-progress task."""

    task_id: str
    chat_session_id: str
    path: str
    operation: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class TaskArtifact:
    """A discoverable artifact associated with a task."""

    id: str
    task_id: str
    kind: ArtifactKind
    name: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskBlocker:
    """Blocking question payload for a task that needs user input."""

    task_id: str
    chat_session_id: str
    question_id: str
    questions: object
    streamed_text: str
    payload: dict[str, Any]
    seen_at: datetime
