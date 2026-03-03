# SPDX-License-Identifier: Apache-2.0

"""Command-line interface for Xolt."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import cast

from xolt import BackendProvisionError, XoltSession
from xolt.backends.base import ExecutionBackend
from xolt.runtimes.base import ManagedRuntime


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
    await session.close()


async def attach_session(args: argparse.Namespace) -> None:
    state = load_state() if args.sandbox_id is None else None
    sandbox_id = args.sandbox_id or (state or {}).get("sandbox_id")
    if not sandbox_id:
        raise SystemExit("No sandbox id provided and no saved Xolt state exists.")
    backend_name = args.backend or (state or {}).get("backend") or default_backend_name()
    runtime_name = args.runtime or (state or {}).get("runtime") or default_runtime_name()
    session_id = args.session_id or (state or {}).get("session_id", "")
    cmd_id = args.cmd_id or (state or {}).get("cmd_id", "")
    session = await XoltSession.attach(
        sandbox_id,
        backend=build_backend(backend_name),
        runtime=build_runtime(runtime_name),
        session_id=session_id,
        cmd_id=cmd_id,
    )
    try:
        print(await session.preview_url())
        print(f"Sandbox: {sandbox_id}")
        print(f"Session: {session.session_id}")
        print(f"Command: {session.cmd_id}")
    finally:
        await session.close()


async def stop_session(args: argparse.Namespace) -> None:
    state = load_state() if args.sandbox_id is None else None
    sandbox_id = args.sandbox_id or (state or {}).get("sandbox_id")
    if not sandbox_id:
        raise SystemExit("No sandbox id provided and no saved Xolt state exists.")
    backend_name = args.backend or (state or {}).get("backend") or default_backend_name()
    runtime_name = args.runtime or (state or {}).get("runtime") or default_runtime_name()
    session = await XoltSession.attach(
        sandbox_id,
        backend=build_backend(backend_name),
        runtime=build_runtime(runtime_name),
        session_id=(state or {}).get("session_id", ""),
        cmd_id=(state or {}).get("cmd_id", ""),
    )
    try:
        await session.delete()
        clear_state()
        print(f"Deleted sandbox {sandbox_id}")
    finally:
        await session.close()


async def with_saved_session() -> XoltSession:
    state = require_state()
    return await XoltSession.attach(
        state["sandbox_id"],
        backend=build_backend(state.get("backend", default_backend_name())),
        runtime=build_runtime(state.get("runtime", default_runtime_name())),
        session_id=state.get("session_id", ""),
        cmd_id=state.get("cmd_id", ""),
    )


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


async def chat(args: argparse.Namespace) -> None:
    session = await with_saved_session()
    try:
        active_session_id = args.session_id
        if args.prompt:
            print(await session.send_message(args.prompt, session_id=active_session_id))
            return

        print("Interactive chat. Type `exit` to quit.")
        while True:
            prompt = input("> ").strip()
            if prompt.lower() in {"exit", "quit"}:
                break
            if not prompt:
                continue
            reply = await session.send_message(prompt, session_id=active_session_id)
            print(reply)
    finally:
        await session.close()


def doctor() -> int:
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
    parser = argparse.ArgumentParser(prog="xolt", description="Managed execution with Xolt.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Create a managed execution session.")
    start_parser.add_argument("--backend", default=None)
    start_parser.add_argument("--runtime", default=None)
    start_parser.add_argument("--skill", action="append", default=[])

    attach_parser = subparsers.add_parser("attach", help="Attach to an existing session.")
    attach_parser.add_argument("sandbox_id", nargs="?")
    attach_parser.add_argument("--backend", default=None)
    attach_parser.add_argument("--runtime", default=None)
    attach_parser.add_argument("--session-id", default="")
    attach_parser.add_argument("--cmd-id", default="")

    stop_parser = subparsers.add_parser("stop", help="Delete a running session.")
    stop_parser.add_argument("sandbox_id", nargs="?")
    stop_parser.add_argument("--backend", default=None)
    stop_parser.add_argument("--runtime", default=None)

    chat_parser = subparsers.add_parser("chat", help="Send prompts to the runtime.")
    chat_parser.add_argument("prompt", nargs="?")
    chat_parser.add_argument("--session-id", default=None)

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
    if args.command == "attach":
        await attach_session(args)
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
