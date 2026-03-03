# SPDX-License-Identifier: Apache-2.0

"""Async client for the OpenCode runtime API."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from xolt.exceptions import FileError, MessageError, SessionError, StreamError

logger = logging.getLogger(__name__)

AUTH_HEADER = "x-daytona-preview-token"


class OpenCodeClient:
    """Low-level async client for the OpenCode server API."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        return {AUTH_HEADER: self._token, "Content-Type": "application/json"}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: float = 300,
    ) -> Any:
        session = await self._get_session()
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        url = f"{self._base_url}{path}"
        try:
            async with session.request(
                method,
                url,
                json=json_body,
                params=params,
                timeout=client_timeout,
            ) as response:
                if response.status == 204:
                    return None
                text = await response.text()
                if response.status >= 400:
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=response.status,
                        message=text,
                    )
                if not text:
                    return None
                return json.loads(text)
        except TimeoutError as exc:
            raise SessionError(f"HTTP {method} {path} timed out after {timeout}s") from exc
        except aiohttp.ClientError as exc:
            raise SessionError(f"HTTP {method} {path} failed: {exc}") from exc

    async def create_session(self, *, title: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        result = await self._request("POST", "/session", json_body=body)
        if not isinstance(result, dict):
            raise SessionError("Unexpected response when creating session")
        return result

    async def list_sessions(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/session")
        if not isinstance(result, list):
            raise SessionError("Unexpected response when listing sessions")
        return result

    async def abort_session(self, session_id: str) -> None:
        await self._request("POST", f"/session/{session_id}/abort")

    async def send_message_async(
        self,
        session_id: str,
        text: str,
        *,
        model: dict[str, str] | None = None,
    ) -> None:
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if model is not None:
            body["model"] = model
        try:
            await self._request("POST", f"/session/{session_id}/prompt_async", json_body=body)
        except SessionError as exc:
            raise MessageError(f"Failed to send async message: {exc}") from exc

    async def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] | None = None
        if limit is not None:
            params = {"limit": str(limit)}
        result = await self._request("GET", f"/session/{session_id}/message", params=params)
        if not isinstance(result, list):
            raise MessageError(f"Unexpected response for messages in session {session_id}")
        return result

    async def list_files(self, path: str | None = None) -> list[dict[str, Any]]:
        resolved = path if path is not None else "."
        try:
            result = await self._request("GET", "/file", params={"path": resolved})
        except SessionError as exc:
            raise FileError(f"Failed to list files at {resolved}: {exc}") from exc
        if not isinstance(result, list):
            raise FileError(f"Unexpected response when listing files at {resolved}")
        return result

    async def read_file(self, path: str) -> dict[str, Any]:
        try:
            result = await self._request("GET", "/file/content", params={"path": path})
        except SessionError as exc:
            raise FileError(f"Failed to read file {path}: {exc}") from exc
        if not isinstance(result, dict):
            raise FileError(f"Unexpected response when reading file {path}")
        return result

    async def file_status(self) -> list[dict[str, Any]]:
        try:
            result = await self._request("GET", "/file/status")
        except SessionError as exc:
            raise FileError(f"Failed to get file status: {exc}") from exc
        if not isinstance(result, list):
            raise FileError("Unexpected response when getting file status")
        return result

    async def find_files(self, query: str) -> list[dict[str, Any]]:
        try:
            result = await self._request("GET", "/find/file", params={"query": query})
        except SessionError as exc:
            raise FileError(f"Failed to find files for '{query}': {exc}") from exc
        if not isinstance(result, list):
            raise FileError(f"Unexpected response when finding files for '{query}'")
        return result

    async def search_in_files(self, pattern: str) -> list[dict[str, Any]]:
        try:
            result = await self._request("GET", "/find", params={"pattern": pattern})
        except SessionError as exc:
            raise FileError(f"Failed to search for '{pattern}': {exc}") from exc
        if not isinstance(result, list):
            raise FileError(f"Unexpected response when searching for '{pattern}'")
        return result

    async def get_session_diff(self, session_id: str) -> list[dict[str, Any]]:
        try:
            result = await self._request("GET", f"/session/{session_id}/diff")
        except SessionError as exc:
            raise FileError(f"Failed to get diff for session {session_id}: {exc}") from exc
        if not isinstance(result, list):
            raise FileError(f"Unexpected response for diff of session {session_id}")
        return result

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        session = await self._get_session()
        url = f"{self._base_url}/event"
        try:
            async with session.get(url) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise StreamError(f"SSE connection failed (HTTP {response.status}): {text}")
                async for raw_line in response.content:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON SSE data: %s", payload)
        except aiohttp.ClientError as exc:
            raise StreamError(f"SSE stream error: {exc}") from exc

    async def set_provider_auth(
        self,
        provider_id: str,
        *,
        auth_type: str = "api",
        key: str,
    ) -> None:
        await self._request(
            "PUT",
            f"/auth/{provider_id}",
            json_body={"type": auth_type, "key": key},
        )
