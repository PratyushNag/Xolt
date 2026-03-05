# SPDX-License-Identifier: Apache-2.0

"""Xolt public package surface."""

from xolt.__about__ import __version__
from xolt.exceptions import (
    AgentError,
    BackendProvisionError,
    FileError,
    MessageError,
    QuestionAskedError,
    RuntimeReloadError,
    SessionError,
    SkillInstallError,
    StreamError,
    XoltError,
)
from xolt.session import XoltSession
from xolt.tasking import (
    TaskArtifact,
    TaskBlocker,
    TaskDiffEntry,
    TaskEvent,
    TaskFileChange,
    TaskHandle,
    TaskResult,
    TaskStatus,
)

__all__ = [
    "AgentError",
    "BackendProvisionError",
    "FileError",
    "MessageError",
    "QuestionAskedError",
    "RuntimeReloadError",
    "SessionError",
    "SkillInstallError",
    "StreamError",
    "TaskArtifact",
    "TaskBlocker",
    "TaskDiffEntry",
    "TaskEvent",
    "TaskFileChange",
    "TaskHandle",
    "TaskResult",
    "TaskStatus",
    "XoltError",
    "XoltSession",
    "__version__",
]
