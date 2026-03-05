# Xolt

Xolt is a sandboxed coding-subagent runtime for agent builders. It lets a parent agent or platform provision an isolated coding agent, equip it with skills and specialist subagents, and interact with it through a Python SDK or CLI.

## Why Xolt Exists

Most agent systems need execution power, but they do not want arbitrary code running inside the host process or product surface. Xolt isolates execution in a sandbox, gives that runtime its own tools, skills, and subagents, and exposes a stable interface back to the parent platform.

The result is a safer and more composable way to add a capable coding subagent to:
- agent platforms
- orchestration frameworks
- IDE integrations
- developer tools
- internal automation systems

## What Xolt Provides

- Provision sandboxed execution runtimes through backend adapters
- Run a dedicated coding subagent in isolation
- Install and manage runtime skills
- Deploy and manage specialist subagents
- Chat with the runtime directly or via SDK
- Inspect files, project trees, and session diffs
- Embed the runtime in higher-level agent systems
- Keep execution isolated from the parent platform

## Architecture

Xolt has three layers:

1. `ExecutionBackend`
   Creates or attaches to a compute environment.
2. `ManagedRuntime`
   Installs and manages the runtime that lives inside that environment.
3. `XoltSession`
   The public orchestration object that binds a backend handle and a runtime handle together.

The first shipped adapters are:

- Backend: Daytona
- Runtime: OpenCode

This is intentionally SDK-first. The CLI is an operator surface over the same primitives.

## SDK Quickstart (Primary Product Surface)

```python
import asyncio

from xolt import XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime


async def main() -> None:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(
            skills=["browser-use/browser-use"],
            agents={
                "reviewer": {
                    "description": "Code review helper",
                    "prompt": "Review changes for correctness, risks, and missing tests.",
                }
            },
        ),
    )
    try:
        chat_id = await session.ensure_chat_session(title="SDK Demo")
        task = await session.submit_task(
            "Summarize the repository structure and list high-risk modules.",
            chat_session_id=chat_id,
            metadata={"source": "readme-demo"},
        )

        async for event in session.stream_task(task.id):
            if event.type == "message_delta":
                print(event.payload.get("delta", ""), end="")

        result = await session.wait_task(task.id, timeout=900)
        print("\nStatus:", result.status)
        print("Final:", result.response)
    finally:
        await session.close()


asyncio.run(main())
```

The SDK exposes:
- runtime lifecycle control
- persistent chat session management
- async task submission, streaming, and waiting
- structured task events for embedding
- explicit task output contracts (`get_task_changes`, `get_task_diff`, `list_task_artifacts`)
- cursor-based stream resume (`stream_task_from(task_id, from_sequence=...)`)
- blocked-task recovery helpers (`is_task_blocked`, `get_task_blocker`, `resume_blocked_task`)
- skill installation and listing
- subagent deployment and removal
- file and project inspection primitives

### Structured Task Events

`stream_task()` emits typed events with a stable envelope:

- `id`
- `type`
- `ts`
- `worker_id`
- `chat_session_id`
- `task_id`
- `sequence`
- `payload`

Current `type` values include:
- `message_delta`
- `status`
- `file_changed`
- `question_asked`
- `runtime_event`

## CLI Quickstart (Companion Operator Surface)

Set credentials in `.env` or your shell:

```bash
DAYTONA_API_KEY=your-api-key
```

Start a sandboxed runtime:

```bash
uv run xolt start --skill browser-use/browser-use
```

Open the operator console:

```bash
uv run xolt attach
```

From there you can:
- chat with the runtime
- list or add skills
- list or add subagents
- inspect files and trees
- inspect session diffs

For automation or scripting, the CLI also supports one-shot commands:

```bash
uv run xolt status
uv run xolt open
uv run xolt chat "Summarize the current project."
uv run xolt skills add browser-use/browser-use
uv run xolt agents list
uv run xolt stop
```

## Interactive Workflow

The recommended human workflow is:

1. `xolt start`
2. `xolt attach`
3. work inside the operator console
4. `xolt stop` when finished

`xolt start` creates the remote runtime and writes a local state file at `~/.xolt/state.json`.

`xolt attach` reads that saved state, reconnects to the running sandbox, validates the runtime is reachable, and opens an interactive console. Exiting the console does not delete the sandbox. `xolt stop` is the explicit destroy action.

Inside the console:

- plain text sends a chat prompt
- `/help` shows commands
- `/status` shows runtime metadata
- `/skills` lists skills
- `/skill add <source>` installs a skill
- `/agents` lists subagents
- `/agent add <name> <path>` adds a subagent
- `/agent remove <name>` removes a subagent
- `/files [path]` lists files
- `/tree [path]` shows a nested tree
- `/diff [session_id]` shows the latest session diff
- `/reload` reloads the runtime
- `/open` prints the preview URL
- `/exit` leaves the console

## Skill and Subagent Model

Xolt treats the runtime as something that can evolve over time:

- skills extend the runtime with reusable capabilities
- subagents add specialist behavior and delegation paths
- the parent agent or platform remains in control through the SDK or CLI

This is the core value proposition: the execution agent is not static. It can be equipped and shaped to match the parent system.

## Sandboxing and Safety Model

Xolt assumes execution belongs inside an isolated environment rather than inside the host application process.

That means:
- the runtime executes inside a sandboxed backend
- the parent application interacts with it through explicit APIs
- operational controls like stop, attach, and inspection are separate from host execution

The exact backend guarantees depend on the configured adapter. Today the shipped production path is Daytona plus OpenCode.

## Integration Scenarios

Xolt is designed for:

- agent platforms that need a coding subagent
- copilots that need isolated code execution
- orchestration systems that want runtime-managed specialists
- IDE experiences that need a delegated execution agent
- products that want project inspection without direct host execution

The CLI is for operators and developers. The SDK is the main embedding surface and primary product focus.

## Embedding Reference Examples

SDK embedding references are provided in `examples/`:

- `embedding_web_backend.py` - stream task events to clients over SSE
- `embedding_queue_worker.py` - run offline queue jobs with SDK task streaming
- `embedding_ide_plugin_loop.py` - plugin-style event bridge with blocked-task recovery

## Current Capabilities and Roadmap

### Working now

- sandbox provisioning through Daytona
- OpenCode runtime startup and attachment
- persistent SDK chat sessions
- SDK task submission and structured event streaming
- skill installation and listing
- subagent deployment and removal
- one-shot chat and interactive console workflows
- file listing, tree inspection, and session diff inspection
- SDK and CLI control over the same runtime

### Partial or evolving

- provider-auth diagnostics for chat failures are improving
- richer operator ergonomics can still improve over time

### Future scope

- richer streaming of project structures and file changes
- broader backend and runtime adapter support
- more advanced operator UX beyond the line-based console

## Development Workflow

```bash
uv sync --group dev
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run ruff check .
uv run ruff format --check .
uv run mypy src/xolt
uv run pytest --cov=src/xolt --cov-report=term-missing
uv run python -m build
```

## Security

Please do not open public issues for security-sensitive reports. Use the process in [SECURITY.md](SECURITY.md).

## License

Xolt is licensed under Apache-2.0. See [LICENSE](LICENSE).
