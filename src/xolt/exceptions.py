# SPDX-License-Identifier: Apache-2.0

"""Exception hierarchy for Xolt."""


class XoltError(Exception):
    """Base exception for all errors raised by Xolt."""


class BackendProvisionError(XoltError):
    """Raised when the execution backend cannot be provisioned or attached."""


class SkillInstallError(XoltError):
    """Raised when a runtime skill fails to install."""


class RuntimeReloadError(XoltError):
    """Raised when a runtime reload operation fails."""


class SessionError(XoltError):
    """Raised when a chat session operation fails."""


class MessageError(XoltError):
    """Raised when sending or receiving a message fails."""


class StreamError(XoltError):
    """Raised when the runtime event stream encounters an error."""


class AgentError(XoltError):
    """Raised when a runtime agent operation fails."""


class FileError(XoltError):
    """Raised when a runtime file operation fails."""


class QuestionAskedError(XoltError):
    """Raised when the runtime asks an interactive question."""

    def __init__(
        self,
        question_id: str,
        session_id: str,
        questions: object,
        streamed_text: str = "",
    ) -> None:
        self.question_id = question_id
        self.session_id = session_id
        self.questions = questions
        self.streamed_text = streamed_text
        super().__init__(f"Runtime asked a question (id={question_id}): {questions}")
