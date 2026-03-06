# SPDX-License-Identifier: Apache-2.0

"""Command-line interface for Xolt."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shlex
import shutil
import sys
import webbrowser
from pathlib import Path
from typing import Any, cast

from xolt import (
    BackendProvisionError,
    MessageError,
    QuestionAskedError,
    TaskBlocker,
    TaskEvent,
    TaskHandle,
    TaskResult,
    XoltSession,
)
from xolt.backends.base import ExecutionBackend
from xolt.runtimes.base import ManagedRuntime

CONSOLE_HELP = """\
Console commands:
  /help                     Show this help
  /status                   Show current runtime metadata
  /open                     Print the preview URL
  /skills                   List installed skills
  /skill add <source>       Install a skill and reload the runtime
  /agents                   List deployed agents
  /agent add <name> <path>  Add an agent from a markdown prompt file
  /agent remove <name>      Remove an agent
  /reload                   Reload the runtime
  /files [path]             List files for a path
  /tree [path]              Show a nested project tree
  /diff [session_id]        Show the latest diff for a chat session
  /exit                     Leave the console without deleting the sandbox

Any non-command input is sent to the active chat session.
"""

COMPANION_HELP = """\
Companion commands:
  /help                     Show this help
  /status                   Show current runtime metadata
  /open                     Print the preview URL
  /skills                   List installed skills
  /add-skill <source>       Install a skill and reload the runtime
  /skill add <source>       Add skill via shorthand (same as /add-skill)
  /agents                   List deployed agents
  /add-agent <name> <path>   Add an agent from a markdown prompt file
  /agent add <name> <path>   Add agent via shorthand
  /remove-agent <name>       Remove an agent
  /agent remove <name>       Remove an agent via shorthand
  /reload                   Reload the runtime
  /files [path]              List files for a path
  /tree [path]               Show a nested project tree
  /cat <path>                Show file content
  /find <query>              Find files by name
  /grep <query>              Search file contents
  /diff [session_id]         Show the latest diff for a chat session
  /abort                     Abort current task
  /raw-event                 Toggle raw event echo for this command
  /exit                      Leave the companion loop without deleting the sandbox

Any non-command input is submitted as a task.
"""


def load_local_env_file(path: Path | None = None) -> None:
    """Load a local .env file into the process environment without overriding exported vars."""

    env_path = path or Path.cwd() / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def get_state_file() -> Path:
    """Return the CLI state file path."""

    configured = os.environ.get("XOLT_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".xolt" / "state.json"


def default_backend_name() -> str:
    return os.environ.get("XOLT_BACKEND", "daytona")


def default_runtime_name() -> str:
    return os.environ.get("XOLT_RUNTIME", "opencode")


def save_state(state: dict[str, str]) -> None:
    path = get_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_state() -> dict[str, str] | None:
    path = get_state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def update_state(patch: dict[str, str]) -> dict[str, str]:
    state = load_state() or {}
    state.update({key: value for key, value in patch.items() if value})
    save_state(state)
    return state


def clear_state() -> None:
    get_state_file().unlink(missing_ok=True)


def require_state() -> dict[str, str]:
    state = load_state()
    if state is None:
        raise SystemExit("No active Xolt session found. Run `xolt start` first.")
    return state


def build_backend(name: str) -> ExecutionBackend:
    if name != "daytona":
        raise SystemExit(f"Unsupported backend: {name}")
    from xolt.backends.daytona import DaytonaBackend

    return cast(ExecutionBackend, DaytonaBackend())


def build_runtime(name: str, *, skills: list[str] | None = None) -> ManagedRuntime:
    if name != "opencode":
        raise SystemExit(f"Unsupported runtime: {name}")
    from xolt.runtimes.opencode import OpenCodeRuntime

    return cast(ManagedRuntime, OpenCodeRuntime(skills=skills))


def _resolve_session_metadata(
    args: argparse.Namespace,
) -> tuple[dict[str, str] | None, str, str, str, str, str, str | None]:
    state = load_state() if getattr(args, "sandbox_id", None) is None else None
    sandbox_id = getattr(args, "sandbox_id", None) or (state or {}).get("sandbox_id")
    if not sandbox_id:
        raise SystemExit("No sandbox id provided and no saved Xolt state exists.")

    backend_name = (
        getattr(args, "backend", None) or (state or {}).get("backend") or default_backend_name()
    )
    runtime_name = (
        getattr(args, "runtime", None) or (state or {}).get("runtime") or default_runtime_name()
    )
    session_id = getattr(args, "session_id", None) or (state or {}).get("session_id", "")
    cmd_id = getattr(args, "cmd_id", None) or (state or {}).get("cmd_id", "")
    chat_session_id = getattr(args, "chat_session_id", None) or (state or {}).get("chat_session_id")
    return state, sandbox_id, backend_name, runtime_name, session_id, cmd_id, chat_session_id


async def _attach_resolved_session(
    sandbox_id: str,
    *,
    backend_name: str,
    runtime_name: str,
    session_id: str,
    cmd_id: str,
) -> XoltSession:
    try:
        return await XoltSession.attach(
            sandbox_id,
            backend=build_backend(backend_name),
            runtime=build_runtime(runtime_name),
            session_id=session_id,
            cmd_id=cmd_id,
        )
    except Exception as exc:
        raise SystemExit(
            f"Failed to attach to sandbox {sandbox_id}. "
            "The saved state may be stale. Run `xolt status` or `xolt stop` to recover."
        ) from exc


async def with_saved_session() -> XoltSession:
    state = require_state()
    return await _attach_resolved_session(
        state["sandbox_id"],
        backend_name=state.get("backend", default_backend_name()),
        runtime_name=state.get("runtime", default_runtime_name()),
        session_id=state.get("session_id", ""),
        cmd_id=state.get("cmd_id", ""),
    )


async def _ensure_chat_session(
    session: XoltSession,
    *,
    sandbox_id: str,
    preferred_session_id: str | None = None,
) -> str:
    if preferred_session_id:
        update_state({"chat_session_id": preferred_session_id})
        return preferred_session_id

    state = load_state() or {}
    existing = state.get("chat_session_id")
    if existing and state.get("sandbox_id") == sandbox_id:
        return existing

    created = await session.create_chat_session(title="Xolt CLI Session")
    chat_session_id = str(created.get("id", "")).strip()
    if not chat_session_id:
        raise SystemExit("Runtime created a chat session without an id.")
    update_state({"chat_session_id": chat_session_id})
    return chat_session_id


def _print_status_summary(
    *,
    state: dict[str, str],
    reachable: bool,
    preview_url: str | None = None,
) -> None:
    print(f"Backend: {state.get('backend', '(unknown)')}")
    print(f"Runtime: {state.get('runtime', '(unknown)')}")
    print(f"Sandbox: {state.get('sandbox_id', '(missing)')}")
    print(f"Runtime Session: {state.get('session_id', '(missing)')}")
    print(f"Runtime Command: {state.get('cmd_id', '(missing)')}")
    print(f"Chat Session: {state.get('chat_session_id', '(none)')}")
    print(f"State File: {get_state_file()}")
    print(f"Reachable: {'yes' if reachable else 'no'}")
    if preview_url:
        print(f"Preview URL: {preview_url}")


def _print_file_listing(entries: list[dict[str, Any]]) -> None:
    if not entries:
        print("(no files)")
        return
    for entry in entries:
        entry_type = entry.get("type", "?")
        path = entry.get("path", "?")
        print(f"{entry_type}: {path}")


def _print_tree(nodes: list[dict[str, Any]], *, indent: int = 0) -> None:
    for node in nodes:
        prefix = "  " * indent
        node_type = node.get("type", "?")
        path = str(node.get("path", "?"))
        print(f"{prefix}{node_type}: {path}")
        children = node.get("children")
        if isinstance(children, list):
            _print_tree(children, indent=indent + 1)


def _print_diff(entries: list[dict[str, Any]]) -> None:
    if not entries:
        print("(no diff entries)")
        return
    for entry in entries:
        path = entry.get("path", "?")
        operation = entry.get("op") or entry.get("status") or "change"
        print(f"{operation}: {path}")


def _print_raw_event(event: dict[str, Any]) -> None:
    try:
        print(json.dumps(event, sort_keys=True))
    except TypeError:
        print(f"raw_event={event}")


def _build_raw_event_from_task_event(event: TaskEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.type == "message_delta":
        return {
            "type": "message.part.delta",
            "properties": {
                "sessionID": event.chat_session_id,
                "delta": payload.get("delta", ""),
                "content": payload.get("delta", ""),
            },
        }
    if event.type == "status":
        return {
            "type": "session.status",
            "properties": {
                "sessionID": event.chat_session_id,
                "status": payload.get("status", "idle"),
            },
        }
    if event.type == "file_changed":
        return {
            "type": "file.edited",
            "properties": {
                "sessionID": event.chat_session_id,
                "file": payload.get("path", ""),
                "op": payload.get("op", "change"),
            },
        }
    if event.type == "question_asked":
        return {
            "type": "question.asked",
            "properties": {
                "id": payload.get("question_id", ""),
                "sessionID": event.chat_session_id,
                "questions": payload.get("questions", []),
            },
        }
    return {
        "type": "runtime.event",
        "properties": {
            "sessionID": event.chat_session_id,
            "taskID": event.task_id,
            "type": event.type,
            "payload": payload,
        },
    }


def _format_task_event(event: TaskEvent) -> None:
    if event.type == "message_delta":
        delta = event.payload.get("delta", "")
        if isinstance(delta, str) and delta:
            print(delta, end="", flush=True)
        return
    if event.type == "file_changed":
        path = str(event.payload.get("path", "?")).strip()
        op = str(event.payload.get("op", "change")).strip() or "change"
        print(f"\n[file_changed] {op}: {path}")
        return
    if event.type == "question_asked":
        raw = event.payload.get("questions", [])
        print("\n[task.blocked] Runtime requested input.")
        if isinstance(raw, list):
            for idx, question in enumerate(raw, start=1):
                print(f"[{idx}] {question}")
        else:
            print(raw)
        return
    if event.type == "status":
        status = event.payload.get("status")
        if status is not None:
            print(f"\n[status] {status}")
            return
        print("\n[status] completed")
        return
    print(f"\n[runtime_event] {event.type}: {event.payload}")


def _print_task_summary(result: TaskResult) -> None:
    print(f"task.completed: {result.task_id}")
    print(f"status: {result.status}")
    if result.error:
        print(f"error: {result.error}")
    if result.response is not None:
        print(f"response: {result.response}")


def _print_chat_error(exc: BaseException) -> None:
    if isinstance(exc, TimeoutError):
        print(
            "Message timed out. The runtime is reachable, but model/provider auth may be missing "
            "or the provider may not be responding.",
            file=sys.stderr,
        )
        return
    if isinstance(exc, QuestionAskedError):
        print(
            f"Runtime asked a question instead of returning a final answer: {exc.questions}",
            file=sys.stderr,
        )
        if exc.streamed_text:
            print(exc.streamed_text, file=sys.stderr)
        return
    if isinstance(exc, MessageError):
        print(str(exc), file=sys.stderr)
        return
    print(f"Chat failed: {exc}", file=sys.stderr)


def _print_blocker(blocker: TaskBlocker) -> None:
    print("Task blocked. Runtime asked:")
    raw_questions = blocker.questions
    if not isinstance(raw_questions, list):
        print(raw_questions)
        return
    questions = [str(question) for question in raw_questions]
    for index, question in enumerate(questions, start=1):
        print(f"{index}. {question}")


async def create_session(args: argparse.Namespace) -> None:
    backend_name = args.backend or default_backend_name()
    runtime_name = args.runtime or default_runtime_name()
    session = await XoltSession.create(
        backend=build_backend(backend_name),
        runtime=build_runtime(runtime_name, skills=args.skill),
    )
    preview_url = await session.preview_url()
    state = {
        "backend": backend_name,
        "runtime": runtime_name,
        "sandbox_id": session.backend.sandbox_id,
        "session_id": session.session_id,
        "cmd_id": session.cmd_id,
    }
    save_state(state)
    print(preview_url)
    print(f"Sandbox: {session.backend.sandbox_id}")
    print(f"State: {get_state_file()}")
    print("Next: run `xolt attach` to open the operator console.")
    await session.close()


async def status_session(args: argparse.Namespace) -> None:
    state, sandbox_id, backend_name, runtime_name, session_id, cmd_id, _ = (
        _resolve_session_metadata(args)
    )
    effective_state = dict(state or {})
    effective_state.update(
        {
            "backend": backend_name,
            "runtime": runtime_name,
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "cmd_id": cmd_id,
        }
    )
    try:
        session = await _attach_resolved_session(
            sandbox_id,
            backend_name=backend_name,
            runtime_name=runtime_name,
            session_id=session_id,
            cmd_id=cmd_id,
        )
    except SystemExit as exc:
        _print_status_summary(state=effective_state, reachable=False)
        print(str(exc), file=sys.stderr)
        raise

    try:
        preview_url = await session.preview_url()
        _print_status_summary(state=effective_state, reachable=True, preview_url=preview_url)
    finally:
        await session.close()


async def open_runtime(args: argparse.Namespace) -> None:
    session = await with_saved_session()
    try:
        preview_url = await session.preview_url()
        print(preview_url)
        if args.browser:
            webbrowser.open(preview_url)
    finally:
        await session.close()


async def stop_session(args: argparse.Namespace) -> None:
    _, sandbox_id, backend_name, runtime_name, session_id, cmd_id, _ = _resolve_session_metadata(
        args
    )
    session = await _attach_resolved_session(
        sandbox_id,
        backend_name=backend_name,
        runtime_name=runtime_name,
        session_id=session_id,
        cmd_id=cmd_id,
    )
    try:
        await session.delete()
        clear_state()
        print(f"Deleted sandbox {sandbox_id}")
    finally:
        await session.close()


async def add_skills(args: argparse.Namespace) -> None:
    session = await with_saved_session()
    try:
        installed, failed = await session.add_skills(args.sources, reload=not args.no_reload)
        print(f"Installed: {', '.join(installed) if installed else '(none)'}")
        if failed:
            print(f"Failed: {', '.join(failed)}", file=sys.stderr)
    finally:
        await session.close()


async def list_runtime_skills() -> None:
    session = await with_saved_session()
    try:
        for skill in await session.list_skills():
            print(skill)
    finally:
        await session.close()


async def reload_runtime() -> None:
    session = await with_saved_session()
    try:
        await session.reload_runtime()
        print("Runtime reloaded")
    finally:
        await session.close()


async def add_agent(args: argparse.Namespace) -> None:
    session = await with_saved_session()
    try:
        prompt = Path(args.path).read_text(encoding="utf-8")
        await session.add_agent(
            args.name,
            {"description": args.description, "mode": "subagent", "prompt": prompt},
            reload=not args.no_reload,
        )
        print(f"Added agent {args.name}")
    finally:
        await session.close()


async def list_agents() -> None:
    session = await with_saved_session()
    try:
        for agent in await session.list_agents():
            print(agent)
    finally:
        await session.close()


async def remove_agent(args: argparse.Namespace) -> None:
    session = await with_saved_session()
    try:
        await session.remove_agent(args.name, reload=not args.no_reload)
        print(f"Removed agent {args.name}")
    finally:
        await session.close()


async def _run_one_shot_chat(
    session: XoltSession,
    prompt: str,
    *,
    sandbox_id: str,
    chat_session_id: str | None,
    raw_events: bool = False,
) -> None:
    event_printer = _print_raw_event if raw_events else None
    try:
        active_chat_session_id = await _ensure_chat_session(
            session,
            sandbox_id=sandbox_id,
            preferred_session_id=chat_session_id,
        )
        print(
            await session.send_message(
                prompt,
                session_id=active_chat_session_id,
                on_event=event_printer,
            )
        )
    except (MessageError, QuestionAskedError, TimeoutError) as exc:
        _print_chat_error(exc)
        raise SystemExit(1) from exc


async def _run_companion_task(
    session: XoltSession,
    prompt: str,
    *,
    chat_session_id: str,
    raw_events: bool = False,
) -> TaskHandle:
    task = await session.submit_task(prompt, chat_session_id=chat_session_id)
    print(f"task.started: {task.id}")
    async for event in session.stream_task(task.id):
        _format_task_event(event)
        if raw_events:
            _print_raw_event(_build_raw_event_from_task_event(event))
    print()
    return task


async def _handle_companion_command(
    session: XoltSession,
    raw_command: str,
    *,
    state: dict[str, str],
    active_chat_session_id: str | None,
    active_task_id: str | None,
    raw_events: bool = False,
) -> tuple[bool, str | None, str | None, bool]:
    parts = shlex.split(raw_command)
    if not parts:
        return False, active_chat_session_id, active_task_id, raw_events

    command = parts[0]
    if command in {"/help"}:
        print(COMPANION_HELP.rstrip())
        return False, active_chat_session_id, active_task_id, raw_events

    if command in {"/exit", "/quit"}:
        return True, active_chat_session_id, active_task_id, raw_events

    if command == "/status":
        preview_url = await session.preview_url()
        state = dict(state)
        if active_chat_session_id:
            state["chat_session_id"] = active_chat_session_id
        _print_status_summary(state=state, reachable=True, preview_url=preview_url)
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/open":
        print(await session.preview_url())
        return False, active_chat_session_id, active_task_id, raw_events

    if command in {"/skill", "/add-skill"} and len(parts) >= 2:
        source = parts[1] if command == "/add-skill" else (parts[2] if len(parts) >= 3 else "")
        if not source:
            print("Usage: /add-skill <source> | /skill add <source>", file=sys.stderr)
            return False, active_chat_session_id, active_task_id, raw_events
        installed, failed = await session.add_skills([source], reload=True)
        print(f"Installed: {', '.join(installed) if installed else '(none)'}")
        if failed:
            print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/skills":
        for skill in await session.list_skills():
            print(skill)
        return False, active_chat_session_id, active_task_id, raw_events

    if command in {"/add-agent", "/agent", "/remove-agent"}:
        if command == "/add-agent":
            if len(parts) != 3:
                print("Usage: /add-agent <name> <path>", file=sys.stderr)
                return False, active_chat_session_id, active_task_id, raw_events
            name, source_path = parts[1], parts[2]
        elif command == "/remove-agent":
            if len(parts) != 2:
                print("Usage: /remove-agent <name>", file=sys.stderr)
                return False, active_chat_session_id, active_task_id, raw_events
            await session.remove_agent(parts[1], reload=True)
            print(f"Removed agent: {parts[1]}")
            return False, active_chat_session_id, active_task_id, raw_events
        else:
            if len(parts) < 3:
                print(
                    "Usage: /agent add <name> <path> | /agent remove <name>",
                    file=sys.stderr,
                )
                return False, active_chat_session_id, active_task_id, raw_events
            action = parts[1]
            if action == "add":
                if len(parts) != 4:
                    print("Usage: /agent add <name> <path>", file=sys.stderr)
                    return False, active_chat_session_id, active_task_id, raw_events
                name, source_path = parts[2], parts[3]
            elif action == "remove":
                if len(parts) != 3:
                    print("Usage: /agent remove <name>", file=sys.stderr)
                    return False, active_chat_session_id, active_task_id, raw_events
                await session.remove_agent(parts[2], reload=True)
                print(f"Removed agent: {parts[2]}")
                return False, active_chat_session_id, active_task_id, raw_events
            else:
                print("Usage: /agent add <name> <path> | /agent remove <name>", file=sys.stderr)
                return False, active_chat_session_id, active_task_id, raw_events

        prompt = Path(source_path).read_text(encoding="utf-8")
        await session.add_agent(
            name,
            {
                "description": f"User-defined Xolt agent ({name})",
                "mode": "subagent",
                "prompt": prompt,
            },
            reload=True,
        )
        print(f"Added agent: {name}")
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/reload":
        await session.reload_runtime()
        print("Runtime reloaded")
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/files":
        file_path = parts[1] if len(parts) > 1 else None
        _print_file_listing(await session.list_files(file_path))
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/tree":
        tree_path = parts[1] if len(parts) > 1 else None
        _print_tree(await session.get_file_tree(tree_path))
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/cat" and len(parts) >= 2:
        content = await session.read_file(parts[1])
        if isinstance(content, dict):
            text = content.get("content")
            if isinstance(text, str):
                print(text)
            else:
                print(content)
        else:
            print(content)
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/find" and len(parts) >= 2:
        for match in await session.find_files(parts[1]):
            print(match)
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/grep" and len(parts) >= 2:
        for match in await session.search_in_files(parts[1]):
            print(match)
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/diff":
        diff_session_id = parts[1] if len(parts) > 1 else active_chat_session_id
        if not diff_session_id:
            print(
                "No chat session id is active yet. Send a prompt first or pass one explicitly.",
                file=sys.stderr,
            )
            return False, active_chat_session_id, active_task_id, raw_events
        _print_diff(await session.get_session_diff(diff_session_id))
        return False, active_chat_session_id, active_task_id, raw_events

    if command == "/abort":
        if not active_task_id:
            print("No active task to abort.")
            return False, active_chat_session_id, active_task_id, raw_events
        await session.cancel_task(active_task_id)
        print(f"task.cancelled: {active_task_id}")
        return False, active_chat_session_id, None, raw_events

    if command == "/raw-event":
        next_state = not raw_events
        print(f"Raw task event output: {'enabled' if next_state else 'disabled'}")
        return False, active_chat_session_id, active_task_id, next_state

    print(f"Unknown companion command: {raw_command}")
    print("Use /help to list supported companion commands.")
    return False, active_chat_session_id, active_task_id, raw_events


async def _resolve_companion_chat_session(
    args: argparse.Namespace,
    session: XoltSession,
) -> str | None:
    if args.chat_session_id:
        resolved_chat_session_id: str = args.chat_session_id
        update_state({"chat_session_id": resolved_chat_session_id})
        return resolved_chat_session_id
    state = load_state() or {}
    raw_existing = state.get("chat_session_id")
    existing = raw_existing.strip() if isinstance(raw_existing, str) else None
    sandbox_id = state.get("sandbox_id")
    if existing and session.backend.sandbox_id == sandbox_id:
        return existing
    created = await session.create_chat_session(title="Xolt CLI Companion Session")
    chat_session_id = str(created.get("id", "")).strip()
    if not chat_session_id:
        raise SystemExit("Runtime created a chat session without an id.")
    update_state({"chat_session_id": chat_session_id})
    return chat_session_id


async def _resume_blocked_task_loop(
    session: XoltSession,
    task: TaskHandle,
    *,
    raw_events: bool = False,
    timeout: float = 900,
) -> TaskResult:
    current_task = task
    while True:
        result = await session.wait_task(current_task.id, timeout=timeout)
        if result.status != "blocked":
            return result
        blocker = session.get_task_blocker(current_task.id)
        if blocker is None:
            return result
        _print_blocker(blocker)
        answer = input(f"answer for {current_task.id}> ").strip()
        if not answer:
            return result
        if answer.lower() in {"/abort", "/cancel"}:
            await session.cancel_task(current_task.id)
            print(f"task.cancelled: {current_task.id}")
            return TaskResult(
                task_id=current_task.id,
                chat_session_id=current_task.chat_session_id,
                status="cancelled",
            )
        current_task = await session.resume_blocked_task(current_task.id, answer)
        if raw_events:
            print(f"task.resumed: {current_task.id}")


async def _handle_console_command(
    session: XoltSession,
    raw_command: str,
    *,
    sandbox_id: str,
    state: dict[str, str],
    active_chat_session_id: str | None,
) -> tuple[bool, str | None]:
    parts = shlex.split(raw_command)
    if not parts:
        return False, active_chat_session_id

    command = parts[0]
    if command in {"/exit", "/quit"}:
        return True, active_chat_session_id

    if command == "/help":
        print(CONSOLE_HELP.rstrip())
        return False, active_chat_session_id

    if command == "/status":
        preview_url = await session.preview_url()
        state = dict(state)
        if active_chat_session_id:
            state["chat_session_id"] = active_chat_session_id
        _print_status_summary(state=state, reachable=True, preview_url=preview_url)
        return False, active_chat_session_id

    if command == "/open":
        print(await session.preview_url())
        return False, active_chat_session_id

    if command == "/skills":
        for skill in await session.list_skills():
            print(skill)
        return False, active_chat_session_id

    if command == "/skill" and len(parts) >= 3 and parts[1] == "add":
        installed, failed = await session.add_skills([parts[2]], reload=True)
        print(f"Installed: {', '.join(installed) if installed else '(none)'}")
        if failed:
            print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return False, active_chat_session_id

    if command == "/agents":
        for agent in await session.list_agents():
            print(agent)
        return False, active_chat_session_id

    if command == "/agent" and len(parts) >= 4 and parts[1] == "add":
        name = parts[2]
        agent_path = Path(parts[3])
        prompt = agent_path.read_text(encoding="utf-8")
        await session.add_agent(
            name,
            {
                "description": f"User-defined Xolt agent ({name})",
                "mode": "subagent",
                "prompt": prompt,
            },
            reload=True,
        )
        print(f"Added agent {name}")
        return False, active_chat_session_id

    if command == "/agent" and len(parts) >= 3 and parts[1] == "remove":
        await session.remove_agent(parts[2], reload=True)
        print(f"Removed agent {parts[2]}")
        return False, active_chat_session_id

    if command == "/reload":
        await session.reload_runtime()
        print("Runtime reloaded")
        return False, active_chat_session_id

    if command == "/files":
        file_path = parts[1] if len(parts) > 1 else None
        _print_file_listing(await session.list_files(file_path))
        return False, active_chat_session_id

    if command == "/tree":
        tree_path = parts[1] if len(parts) > 1 else None
        _print_tree(await session.get_file_tree(tree_path))
        return False, active_chat_session_id

    if command == "/diff":
        diff_session_id = parts[1] if len(parts) > 1 else active_chat_session_id
        if not diff_session_id:
            print(
                "No chat session id is active yet. Send a prompt first or pass one explicitly.",
                file=sys.stderr,
            )
            return False, active_chat_session_id
        _print_diff(await session.get_session_diff(diff_session_id))
        return False, active_chat_session_id

    print(f"Unknown console command: {raw_command}", file=sys.stderr)
    print("Use /help to list supported console commands.", file=sys.stderr)
    return False, active_chat_session_id


async def console_session(args: argparse.Namespace) -> None:
    (
        state,
        sandbox_id,
        backend_name,
        runtime_name,
        session_id,
        cmd_id,
        chat_session_id,
    ) = _resolve_session_metadata(args)
    session = await _attach_resolved_session(
        sandbox_id,
        backend_name=backend_name,
        runtime_name=runtime_name,
        session_id=session_id,
        cmd_id=cmd_id,
    )
    try:
        preview_url = await session.preview_url()
        effective_state = dict(state or {})
        effective_state.update(
            {
                "backend": backend_name,
                "runtime": runtime_name,
                "sandbox_id": sandbox_id,
                "session_id": session_id,
                "cmd_id": cmd_id,
            }
        )
        if chat_session_id:
            effective_state["chat_session_id"] = chat_session_id

        print(f"Attached to sandbox {sandbox_id}")
        print(f"Preview: {preview_url}")
        print("Operator console ready. Type /help for commands. Type /exit to leave.")

        active_chat_session_id = chat_session_id
        while True:
            raw = input("xolt> ").strip()
            if not raw:
                continue

            if raw.startswith("/"):
                should_exit, active_chat_session_id = await _handle_console_command(
                    session,
                    raw,
                    sandbox_id=sandbox_id,
                    state=effective_state,
                    active_chat_session_id=active_chat_session_id,
                )
                if active_chat_session_id:
                    effective_state["chat_session_id"] = active_chat_session_id
                if should_exit:
                    break
                continue

            try:
                event_printer = _print_raw_event if args.raw_event else None
                active_chat_session_id = await _ensure_chat_session(
                    session,
                    sandbox_id=sandbox_id,
                    preferred_session_id=active_chat_session_id,
                )
                effective_state["chat_session_id"] = active_chat_session_id
                print(
                    await session.send_message(
                        raw,
                        session_id=active_chat_session_id,
                        on_event=event_printer,
                    )
                )
            except (MessageError, QuestionAskedError, TimeoutError) as exc:
                _print_chat_error(exc)
    finally:
        await session.close()


async def companion_session(args: argparse.Namespace) -> None:
    (
        state,
        sandbox_id,
        backend_name,
        runtime_name,
        session_id,
        cmd_id,
        chat_session_id,
    ) = _resolve_session_metadata(args)
    session = await _attach_resolved_session(
        sandbox_id,
        backend_name=backend_name,
        runtime_name=runtime_name,
        session_id=session_id,
        cmd_id=cmd_id,
    )
    effective_state = dict(state or {})
    effective_state.update(
        {
            "backend": backend_name,
            "runtime": runtime_name,
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "cmd_id": cmd_id,
        }
    )
    if chat_session_id:
        effective_state["chat_session_id"] = chat_session_id
    active_task_id: str | None = None
    raw_events = bool(getattr(args, "raw_event", False))

    try:
        preview_url = await session.preview_url()
        print(f"Attached to sandbox {sandbox_id}")
        print(f"Preview: {preview_url}")
        print("Parent-platform companion ready. Type /help for commands. Type /exit to leave.")

        active_chat_session_id: str | None = await _resolve_companion_chat_session(args, session)
        effective_state["chat_session_id"] = active_chat_session_id

        while True:
            raw = input("xolt> ").strip()
            if not raw:
                continue

            if raw.startswith("/"):
                (
                    should_exit,
                    active_chat_session_id,
                    active_task_id,
                    raw_events,
                ) = await _handle_companion_command(
                    session,
                    raw,
                    state=effective_state,
                    active_chat_session_id=active_chat_session_id,
                    active_task_id=active_task_id,
                    raw_events=raw_events,
                )
                if active_chat_session_id:
                    effective_state["chat_session_id"] = active_chat_session_id
                if should_exit:
                    break
                continue

            task = await _run_companion_task(
                session,
                raw,
                chat_session_id=active_chat_session_id,
                raw_events=raw_events,
            )
            active_task_id = task.id
            result = await _resolve_companion_result(
                session,
                task.id,
                timeout=getattr(args, "timeout", 900),
            )
            if result.status == "blocked":
                result = await _resume_blocked_task_loop(
                    session,
                    task,
                    raw_events=raw_events,
                    timeout=getattr(args, "timeout", 900),
                )
            _print_task_summary(result)
            active_task_id = None
    finally:
        await session.close()


async def _resolve_companion_result(
    session: XoltSession,
    task_id: str,
    *,
    timeout: float = 900,
) -> TaskResult:
    return await session.wait_task(task_id, timeout=timeout)


async def chat(args: argparse.Namespace) -> None:
    if args.interactive or args.prompt is None:
        console_args = argparse.Namespace(
            sandbox_id=None,
            backend=None,
            runtime=None,
            session_id="",
            cmd_id="",
            chat_session_id=args.session_id,
            raw_event=args.raw_event,
        )
        await console_session(console_args)
        return

    state = require_state()
    session = await with_saved_session()
    try:
        await _run_one_shot_chat(
            session,
            args.prompt,
            sandbox_id=state["sandbox_id"],
            chat_session_id=args.session_id or state.get("chat_session_id"),
            raw_events=args.raw_event,
        )
    finally:
        await session.close()


def doctor() -> int:
    load_local_env_file()
    backend_name = default_backend_name()
    runtime_name = default_runtime_name()
    issues: list[str] = []

    if shutil.which("uv") is None:
        issues.append("uv is not installed or not on PATH.")
    if backend_name != "daytona":
        issues.append(f"Unsupported backend configured in XOLT_BACKEND: {backend_name}")
    if runtime_name != "opencode":
        issues.append(f"Unsupported runtime configured in XOLT_RUNTIME: {runtime_name}")
    if not os.environ.get("DAYTONA_API_KEY"):
        issues.append("DAYTONA_API_KEY is not set.")

    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1

    print("Xolt doctor checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xolt",
        description="Sandboxed coding subagents for agent builders.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Create a managed execution session.")
    start_parser.add_argument("--backend", default=None)
    start_parser.add_argument("--runtime", default=None)
    start_parser.add_argument("--skill", action="append", default=[])

    attach_parser = subparsers.add_parser(
        "attach",
        help="Attach to the saved runtime and open the operator console.",
    )
    attach_parser.add_argument("sandbox_id", nargs="?")
    attach_parser.add_argument("--backend", default=None)
    attach_parser.add_argument("--runtime", default=None)
    attach_parser.add_argument("--session-id", default="")
    attach_parser.add_argument("--cmd-id", default="")
    attach_parser.add_argument("--chat-session-id", default=None)
    attach_parser.add_argument("--raw-event", action="store_true")

    console_parser = subparsers.add_parser(
        "console",
        help="Alias for `xolt attach`.",
    )
    console_parser.add_argument("sandbox_id", nargs="?")
    console_parser.add_argument("--backend", default=None)
    console_parser.add_argument("--runtime", default=None)
    console_parser.add_argument("--session-id", default="")
    console_parser.add_argument("--cmd-id", default="")
    console_parser.add_argument("--chat-session-id", default=None)
    console_parser.add_argument("--raw-event", action="store_true")

    companion_parser = subparsers.add_parser(
        "companion",
        help="Parent-platform simulation loop.",
    )
    companion_parser.add_argument("sandbox_id", nargs="?")
    companion_parser.add_argument("--backend", default=None)
    companion_parser.add_argument("--runtime", default=None)
    companion_parser.add_argument("--session-id", default="")
    companion_parser.add_argument("--cmd-id", default="")
    companion_parser.add_argument("--chat-session-id", default=None)
    companion_parser.add_argument(
        "--raw-event", "--raw-events", dest="raw_event", action="store_true"
    )
    companion_parser.add_argument("--timeout", type=float, default=900)

    status_parser = subparsers.add_parser("status", help="Show runtime metadata and reachability.")
    status_parser.add_argument("sandbox_id", nargs="?")
    status_parser.add_argument("--backend", default=None)
    status_parser.add_argument("--runtime", default=None)
    status_parser.add_argument("--session-id", default="")
    status_parser.add_argument("--cmd-id", default="")
    status_parser.add_argument("--chat-session-id", default=None)

    open_parser = subparsers.add_parser("open", help="Print the current preview URL.")
    open_parser.add_argument("--browser", action="store_true")

    stop_parser = subparsers.add_parser("stop", help="Delete a running session.")
    stop_parser.add_argument("sandbox_id", nargs="?")
    stop_parser.add_argument("--backend", default=None)
    stop_parser.add_argument("--runtime", default=None)
    stop_parser.add_argument("--session-id", default="")
    stop_parser.add_argument("--cmd-id", default="")
    stop_parser.add_argument("--chat-session-id", default=None)

    chat_parser = subparsers.add_parser("chat", help="Send prompts to the runtime.")
    chat_parser.add_argument("prompt", nargs="?")
    chat_parser.add_argument("--session-id", default=None)
    chat_parser.add_argument("--interactive", action="store_true")
    chat_parser.add_argument("--raw-event", action="store_true")

    skills_parser = subparsers.add_parser("skills", help="Manage runtime skills.")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_add_parser = skills_subparsers.add_parser("add", help="Install runtime skills.")
    skills_add_parser.add_argument("sources", nargs="+")
    skills_add_parser.add_argument("--no-reload", action="store_true")
    skills_subparsers.add_parser("list", help="List installed skills.")

    runtime_parser = subparsers.add_parser("runtime", help="Runtime lifecycle commands.")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_subparsers.add_parser("reload", help="Reload the running runtime.")

    agents_parser = subparsers.add_parser("agents", help="Manage runtime agents.")
    agents_subparsers = agents_parser.add_subparsers(dest="agents_command", required=True)
    agents_add_parser = agents_subparsers.add_parser("add", help="Add an agent from a prompt file.")
    agents_add_parser.add_argument("name")
    agents_add_parser.add_argument("path")
    agents_add_parser.add_argument("--description", default="User-defined Xolt agent")
    agents_add_parser.add_argument("--no-reload", action="store_true")
    agents_subparsers.add_parser("list", help="List agents.")
    agents_remove_parser = agents_subparsers.add_parser("remove", help="Remove an agent.")
    agents_remove_parser.add_argument("name")
    agents_remove_parser.add_argument("--no-reload", action="store_true")

    subparsers.add_parser("doctor", help="Validate the local Xolt environment.")
    return parser


async def run_async(args: argparse.Namespace) -> int:
    if args.command == "start":
        await create_session(args)
        return 0
    if args.command in {"attach", "console"}:
        await console_session(args)
        return 0
    if args.command == "companion":
        await companion_session(args)
        return 0
    if args.command == "status":
        await status_session(args)
        return 0
    if args.command == "open":
        await open_runtime(args)
        return 0
    if args.command == "stop":
        await stop_session(args)
        return 0
    if args.command == "chat":
        await chat(args)
        return 0
    if args.command == "skills":
        if args.skills_command == "add":
            await add_skills(args)
            return 0
        await list_runtime_skills()
        return 0
    if args.command == "runtime":
        await reload_runtime()
        return 0
    if args.command == "agents":
        if args.agents_command == "add":
            await add_agent(args)
            return 0
        if args.agents_command == "list":
            await list_agents()
            return 0
        await remove_agent(args)
        return 0
    if args.command == "doctor":
        return doctor()
    raise SystemExit(f"Unsupported command: {args.command}")


def main() -> None:
    load_local_env_file()
    log_level = os.environ.get("XOLT_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING))
    parser = build_parser()
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(run_async(args))
    except BackendProvisionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
