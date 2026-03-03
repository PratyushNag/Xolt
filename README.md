# Xolt

Xolt is a managed execution system with a production-ready Python SDK and CLI. It separates the execution backend from the runtime layer so teams can start with Daytona + OpenCode today and extend the platform later without rewriting the public surface.

## What Xolt Does

- Provisions managed execution environments through backend adapters
- Starts and controls interactive runtimes through runtime adapters
- Ships a real CLI for starting, attaching, stopping, and operating sessions
- Exposes a Python SDK for applications that need programmatic control
- Standardizes local development with `uv`, `ruff`, `mypy`, `pytest`, and `pre-commit`

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

## Install

### End users

```bash
uv tool install .
```

### Contributors

```bash
uv sync --group dev
uv run pre-commit install
```

## CLI Quickstart

Set your backend credentials:

```bash
export DAYTONA_API_KEY="your-api-key"
```

Start a new session:

```bash
uv run xolt start
```

Attach to the saved session:

```bash
uv run xolt attach
```

Install runtime skills:

```bash
uv run xolt skills add browser-use/browser-use
```

Reload the runtime after changes:

```bash
uv run xolt runtime reload
```

Run environment checks:

```bash
uv run xolt doctor
```

## SDK Quickstart

```python
import asyncio

from xolt import XoltSession
from xolt.backends.daytona import DaytonaBackend
from xolt.runtimes.opencode import OpenCodeRuntime


async def main() -> None:
    session = await XoltSession.create(
        backend=DaytonaBackend(),
        runtime=OpenCodeRuntime(skills=["browser-use/browser-use"]),
    )
    try:
        print(await session.preview_url())
    finally:
        await session.close()


asyncio.run(main())
```

## Adapter Model

Xolt intentionally keeps backend-specific and runtime-specific logic out of the top-level package import.

- `xolt` imports only the public session and exceptions
- `xolt.backends.daytona` contains the Daytona adapter
- `xolt.runtimes.opencode` contains the OpenCode adapter

This keeps `import xolt` lightweight and gives future adapters a clean integration point.

## Development Workflow

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/xolt
uv run pytest
uv run python -m build
```

## Security

Please do not open public issues for security-sensitive reports. Use the process in [SECURITY.md](SECURITY.md).

## License

Xolt is licensed under Apache-2.0. See [LICENSE](LICENSE).
