# SPDX-License-Identifier: Apache-2.0

"""Parent-platform reference flow for the Xolt SDK CLI experience."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from xolt import MessageError, QuestionAskedError, XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime

DEFAULT_PROMPTS = (
    "List three concrete files in the workspace with a short summary.",
    "Create a short markdown report at runbook.md with a title and one paragraph.",
)


def _print_raw_event(event: dict[str, Any]) -> None:
    print(f"RAW {json.dumps(event, sort_keys=True)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic parent-platform companion flow."
    )
    parser.add_argument(
        "--raw-event",
        action="store_true",
        help="Print raw event payloads during send_message.",
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Install an additional skill before the first message.",
    )
    parser.add_argument(
        "--agent-name",
        default=None,
        help="Optional agent name to add during the flow.",
    )
    parser.add_argument(
        "--agent-prompt-path",
        default=None,
        help="Markdown file path used for the temporary agent prompt.",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=list(DEFAULT_PROMPTS),
        help="Prompt to send as a parent-platform task (repeatable).",
    )
    parser.add_argument(
        "--keep-runtime",
        action="store_true",
        help="Keep the runtime alive after the run instead of deleting it.",
    )
    return parser


def _load_agent_prompt(path: str | None) -> str:
    if not path:
        return "User-defined reviewer agent"
    resolved = path if os.path.isabs(path) else str((Path.cwd() / path).resolve())
    return Path(resolved).read_text(encoding="utf-8")


async def run_flow(args: argparse.Namespace) -> None:
    if not os.environ.get("DAYTONA_API_KEY"):
        raise SystemExit("DAYTONA_API_KEY is required to run runtime examples.")

    runtime = OpenCodeRuntime(skills=args.skill or None)
    session = await XoltSession.create(backend=DaytonaBackend(), runtime=runtime)
    event_printer = _print_raw_event if args.raw_event else None

    try:
        print(f"Sandbox: {session.backend.sandbox_id}")
        print(f"Runtime session: {session.session_id}")
        print(f"Runtime command: {session.cmd_id}")
        print(f"Preview: {await session.preview_url()}")

        print("Installed skills:", ", ".join(await session.list_skills()) or "(none)")
        chat_session = await session.create_chat_session(title="Parent platform companion session")
        chat_session_id = str(chat_session.get("id", "")).strip()

        if args.agent_name and args.agent_prompt_path:
            await session.add_agent(
                args.agent_name,
                {
                    "description": f"Temporary {args.agent_name} agent",
                    "mode": "subagent",
                    "prompt": _load_agent_prompt(args.agent_prompt_path),
                },
                reload=False,
            )
            print(f"Added agent: {args.agent_name}")

        print("Agents:", ", ".join(await session.list_agents()) or "(none)")

        for index, prompt in enumerate(args.prompt, start=1):
            print(f"\n[task-{index}] {prompt}")
            reply = await session.send_message(
                prompt,
                session_id=chat_session_id,
                on_event=event_printer,
            )
            print(f"[task-{index}-reply]\n{reply}")

        diff_entries = await session.get_session_diff(chat_session_id)
        print("\nSession diff:")
        for entry in diff_entries:
            print(f"{entry.get('op', 'change')}: {entry.get('path', '?')}")

        files = await session.list_files("README.md")
        print(f"README file status: {files}")

    except (MessageError, QuestionAskedError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        if args.keep_runtime:
            print(f"Keeping runtime {session.backend.sandbox_id} for inspection.")
        else:
            await session.delete()
            print(f"Deleted runtime {session.backend.sandbox_id}.")
        await session.close()


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(run_flow(args))
    except KeyboardInterrupt as exc:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
