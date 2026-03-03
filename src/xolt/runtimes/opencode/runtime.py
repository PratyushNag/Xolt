# SPDX-License-Identifier: Apache-2.0

"""OpenCode runtime adapter for Xolt."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from xolt.backends.base import BackendHandle
from xolt.exceptions import FileError, MessageError, QuestionAskedError
from xolt.runtimes.base import EventCallback
from xolt.runtimes.opencode.agents import (
    deploy_agent,
    list_deployed_agents,
    remove_agent_file,
)
from xolt.runtimes.opencode.client import OpenCodeClient
from xolt.runtimes.opencode.config import (
    BACKEND_PORT,
    MANAGE_SKILLS_SANDBOX_DIR,
    MANAGE_SKILLS_SANDBOX_PATH,
    PROXY_SCRIPT_SANDBOX_PATH,
    PUBLIC_PORT,
    RELOAD_FLAG_PATH,
    build_opencode_config,
    get_manage_skills_markdown,
    get_proxy_script,
    get_skills_from_env,
)
from xolt.runtimes.opencode.skills import (
    dispose_all_instances,
    install_skills,
    list_skills,
)
from xolt.runtimes.opencode.types import AgentConfig

logger = logging.getLogger(__name__)


class OpenCodeRuntimeHandle:
    """Live OpenCode runtime instance bound to a backend handle."""

    _WATCHER_OP: ClassVar[dict[str, str]] = {
        "add": "add",
        "addDir": "add_dir",
        "change": "edit",
        "unlink": "delete",
        "unlinkDir": "delete_dir",
    }

    def __init__(
        self,
        backend: BackendHandle,
        *,
        session_id: str,
        cmd_id: str,
        port: int = PUBLIC_PORT,
        installed_skills: list[str] | None = None,
        deployed_agents: list[str] | None = None,
    ) -> None:
        self._backend = backend
        self._sandbox = backend.sandbox
        self._client: OpenCodeClient | None = None
        self.session_id = session_id
        self.cmd_id = cmd_id
        self.port = port
        self.installed_skills = list(installed_skills or [])
        self.deployed_agents = list(deployed_agents or [])

    @property
    def sandbox(self) -> Any:
        return self._sandbox

    async def preview_url(self) -> str:
        return (await self._backend.get_preview_access(self.port)).url

    async def _get_client(self) -> OpenCodeClient:
        if self._client is None:
            preview = await self._backend.get_preview_access(self.port)
            self._client = OpenCodeClient(base_url=preview.url, token=preview.token)
        return self._client

    async def add_skill(self, skill_source: str, *, reload: bool = True) -> bool:
        installed, _ = await self.add_skills([skill_source], reload=reload)
        return bool(installed)

    async def add_skills(
        self,
        skills: list[str],
        *,
        reload: bool = True,
    ) -> tuple[list[str], list[str]]:
        installed, failed = await install_skills(self._sandbox, skills)
        self.installed_skills.extend(installed)
        if installed and reload:
            await self.reload_runtime()
        return installed, failed

    async def reload_runtime(self) -> None:
        await dispose_all_instances(self._sandbox)

    async def _check_and_dispose(self) -> bool:
        try:
            result = await self._sandbox.process.exec(
                f"test -f {RELOAD_FLAG_PATH} && echo EXISTS || echo MISSING",
                timeout=5,
            )
        except Exception:
            logger.debug("Could not check reload flag")
            return False

        if result.exit_code == 0 and "EXISTS" in (result.result or ""):
            await dispose_all_instances(self._sandbox)
            await self._sandbox.process.exec(f"rm -f {RELOAD_FLAG_PATH}", timeout=5)
            return True
        return False

    async def list_skills(self) -> list[str]:
        return await list_skills(self._sandbox)

    async def add_agent(
        self,
        name: str,
        config: AgentConfig,
        *,
        reload: bool = True,
    ) -> None:
        await deploy_agent(self._sandbox, name, config)
        if name not in self.deployed_agents:
            self.deployed_agents.append(name)
        if reload:
            await dispose_all_instances(self._sandbox)

    async def remove_agent(self, name: str, *, reload: bool = True) -> None:
        await remove_agent_file(self._sandbox, name)
        if name in self.deployed_agents:
            self.deployed_agents.remove(name)
        if reload:
            await dispose_all_instances(self._sandbox)

    async def list_agents(self) -> list[str]:
        return await list_deployed_agents(self._sandbox)

    async def create_chat_session(self, *, title: str | None = None) -> dict[str, Any]:
        client = await self._get_client()
        return await client.create_session(title=title)

    async def list_chat_sessions(self) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.list_sessions()

    async def send_message(
        self,
        text: str,
        *,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
        on_event: EventCallback = None,
        timeout: float = 900,
    ) -> str:
        await self._check_and_dispose()
        client = await self._get_client()
        active_session_id = session_id
        if active_session_id is None:
            session = await client.create_session()
            active_session_id = str(session["id"])

        stream_task = asyncio.create_task(self._wait_for_idle(on_event=on_event))
        try:
            await client.send_message_async(active_session_id, text, model=model)
            streamed_text = await asyncio.wait_for(stream_task, timeout=timeout)
        except BaseException:
            stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stream_task
            raise

        messages = await client.list_messages(active_session_id)
        response = self.extract_response(messages)
        if streamed_text and self._is_raw_fallback(response):
            response = streamed_text.strip()
        await self._check_and_dispose()
        return response

    async def send_message_async(
        self,
        text: str,
        *,
        session_id: str | None = None,
        model: dict[str, str] | None = None,
    ) -> str:
        client = await self._get_client()
        active_session_id = session_id
        if active_session_id is None:
            session = await client.create_session()
            active_session_id = str(session["id"])
        await client.send_message_async(active_session_id, text, model=model)
        return active_session_id

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        client = await self._get_client()
        async for event in client.stream_events():
            yield event

    async def _wait_for_idle(self, *, on_event: EventCallback = None) -> str:
        streamed_chunks: list[str] = []
        async for event in self.stream_events():
            if on_event is not None:
                callback_result = on_event(event)
                if inspect.isawaitable(callback_result):
                    await callback_result

            event_type = event.get("type", "")
            if event_type == "message.part.delta":
                props = event.get("properties", {})
                delta = props.get("delta", props.get("content", ""))
                if isinstance(delta, str) and delta:
                    streamed_chunks.append(delta)

            if event_type == "question.asked":
                props = event.get("properties", {})
                raise QuestionAskedError(
                    question_id=str(props.get("id", "")),
                    session_id=str(props.get("sessionID", "")),
                    questions=props.get("questions", []),
                    streamed_text="".join(streamed_chunks),
                )

            if event_type == "session.status":
                props = event.get("properties", {})
                if props.get("status") == "idle":
                    break

        return "".join(streamed_chunks)

    async def abort(self, session_id: str) -> None:
        client = await self._get_client()
        await client.abort_session(session_id)

    async def get_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.list_messages(session_id, limit=limit)

    async def set_provider_auth(
        self,
        provider_id: str,
        *,
        key: str,
        auth_type: str = "api",
    ) -> None:
        client = await self._get_client()
        await client.set_provider_auth(provider_id, auth_type=auth_type, key=key)

    async def list_files(self, path: str | None = None) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.list_files(path)

    async def get_file_tree(
        self,
        path: str | None = None,
        *,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        nodes = await self.list_files(path)
        if max_depth <= 0:
            return nodes
        directories = [node for node in nodes if node.get("type") == "directory"]
        if not directories:
            return nodes

        results = await asyncio.gather(
            *(self.get_file_tree(entry["path"], max_depth=max_depth - 1) for entry in directories),
            return_exceptions=True,
        )
        child_map: dict[str, list[dict[str, Any]]] = {}
        for directory, result in zip(directories, results, strict=True):
            if isinstance(result, BaseException):
                child_map[str(directory["path"])] = []
            else:
                child_map[str(directory["path"])] = result

        enriched: list[dict[str, Any]] = []
        for node in nodes:
            node_path = node.get("path")
            if node.get("type") == "directory" and node_path in child_map:
                enriched.append({**node, "children": child_map[str(node_path)]})
            else:
                enriched.append(node)
        return enriched

    async def read_file(self, path: str) -> dict[str, Any]:
        client = await self._get_client()
        return await client.read_file(path)

    async def file_status(self) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.file_status()

    async def find_files(self, query: str) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.find_files(query)

    async def search_in_files(self, pattern: str) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.search_in_files(pattern)

    async def get_session_diff(self, session_id: str | None = None) -> list[dict[str, Any]]:
        if session_id is None:
            raise FileError(
                "session_id is required for get_session_diff(). "
                "Pass the session ID from create_chat_session() or send_message_async()."
            )
        client = await self._get_client()
        return await client.get_session_diff(session_id)

    async def delete(self) -> None:
        await self._backend.delete()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        await self._backend.close()

    @staticmethod
    def extract_text(message: dict[str, Any]) -> str:
        parts = message.get("parts", [])
        if not isinstance(parts, list):
            return str(message)
        texts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        ]
        return "\n".join(texts) if texts else str(message)

    @classmethod
    def extract_response(cls, messages: list[dict[str, Any]]) -> str:
        assistants = [
            message
            for message in messages
            if isinstance(message, dict)
            and isinstance(message.get("info"), dict)
            and message["info"].get("role") == "assistant"
        ]
        if not assistants:
            return "(no response)"
        message = assistants[-1]
        info = message.get("info", {})
        if isinstance(info, dict) and info.get("error"):
            raise MessageError(f"Agent error: {info['error']}")
        return cls.extract_text(message) or "(no response)"

    @staticmethod
    def _is_raw_fallback(text: str) -> bool:
        stripped = text.lstrip()
        return not text or text == "(no response)" or (
            stripped.startswith("{") and "'info'" in stripped
        )

    @staticmethod
    def classify_file_event(event: dict[str, Any]) -> dict[str, str] | None:
        event_type = event.get("type", "")
        props = event.get("properties", {})
        if event_type == "file.edited":
            path = props.get("file", "")
            return {"op": "edit", "path": path} if path else None
        if event_type == "file.watcher.updated":
            watcher_event = props.get("event", "")
            path = props.get("file", "")
            operation = OpenCodeRuntimeHandle._WATCHER_OP.get(watcher_event)
            if operation and path:
                return {"op": operation, "path": path}
            return None
        if event_type == "session.status" and props.get("status") == "idle":
            return {"op": "reconcile"}
        return None


class OpenCodeRuntime:
    """Runtime adapter that installs and runs OpenCode inside a backend."""

    name = "opencode"

    def __init__(
        self,
        *,
        skills: list[str] | None = None,
        agents: dict[str, AgentConfig] | None = None,
        port: int = PUBLIC_PORT,
    ) -> None:
        self.skills = list(skills) if skills is not None else None
        self.agents = dict(agents) if agents is not None else None
        self.port = port

    async def start(self, backend: BackendHandle) -> OpenCodeRuntimeHandle:
        from daytona import SessionExecuteRequest

        sandbox = backend.sandbox
        try:
            install_result = await sandbox.process.exec(
                "npm i -g opencode-ai@latest",
                timeout=180,
            )
            if install_result.exit_code != 0:
                raise MessageError(f"Failed to install OpenCode: {install_result.result}")

            await sandbox.process.exec("npx -y skills --help", timeout=120)
            await sandbox.process.exec(f"mkdir -p {MANAGE_SKILLS_SANDBOX_DIR}", timeout=5)
            await sandbox.fs.upload_file(
                get_manage_skills_markdown().encode(),
                MANAGE_SKILLS_SANDBOX_PATH,
            )
            await sandbox.fs.upload_file(
                get_proxy_script().encode(),
                PROXY_SCRIPT_SANDBOX_PATH,
            )

            initial_skills = self.skills if self.skills is not None else get_skills_from_env()
            installed_skills: list[str] = []
            if initial_skills:
                installed_skills, _ = await install_skills(sandbox, initial_skills)

            deployed_agents: list[str] = []
            if self.agents:
                for agent_name, agent_cfg in self.agents.items():
                    if agent_name == "daytona":
                        continue
                    await deploy_agent(sandbox, agent_name, agent_cfg)
                    deployed_agents.append(agent_name)

            env_var, _ = await build_opencode_config(sandbox, agents=self.agents)
            session_id = f"xolt-runtime-{int(asyncio.get_running_loop().time())}"
            await sandbox.process.create_session(session_id)
            command = await sandbox.process.execute_session_command(
                session_id,
                SessionExecuteRequest(
                    command=f"{env_var} opencode web --port {BACKEND_PORT}",
                    run_async=True,
                ),
            )
            if not command.cmd_id:
                raise MessageError("Failed to start OpenCode command in sandbox")

            await sandbox.process.exec(
                f"PROXY_PORT={self.port} BACKEND_PORT={BACKEND_PORT} "
                f"nohup node {PROXY_SCRIPT_SANDBOX_PATH} > /tmp/proxy.log 2>&1 &",
                timeout=10,
            )

            return OpenCodeRuntimeHandle(
                backend,
                session_id=session_id,
                cmd_id=str(command.cmd_id),
                port=self.port,
                installed_skills=installed_skills,
                deployed_agents=deployed_agents,
            )
        except Exception:
            with contextlib.suppress(Exception):
                await backend.delete()
            await backend.close()
            raise

    async def attach(
        self,
        backend: BackendHandle,
        *,
        session_id: str = "",
        cmd_id: str = "",
    ) -> OpenCodeRuntimeHandle:
        return OpenCodeRuntimeHandle(
            backend,
            session_id=session_id,
            cmd_id=cmd_id,
            port=self.port,
        )
