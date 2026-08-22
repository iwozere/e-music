# Agent & Contributor Guide — MySpotify (e-music)

This document describes the conventions and working agreements for **MySpotify**, a
self-hosted music platform. It is binding for both human developers and AI agents
contributing to the codebase. It is the single source of truth for style, repo
layout, tooling, and the run/test/deploy workflow.

---

## 0. Project Overview

MySpotify is a **monorepo** with three deliverables:

| Path | Stack | Purpose |
|------|-------|---------|
| `backend/` | Python 3.13, **FastAPI**, SQLModel, Alembic | API, streaming pipeline, library indexer |
| `backend/app/static/` | **Vanilla JS** (no build step), HTML, CSS | Web player UI |
| `mobile/` | **Flutter / Dart** (BLoC) | Android/iOS app |

Runtime context:

- Designed to run on a **Raspberry Pi 5** via **Docker** (`docker-compose.yml`),
  sitting behind an external HTTPS reverse proxy / tunnel.
- Audio comes from the **local library** and **YouTube Music** (resolved via `yt-dlp`,
  re-muxed/transcoded with **ffmpeg**; `n`-signature solving needs **Deno or Node 20+**).
- Persistence is **SQLite** (`app/db/`) managed through **Alembic** migrations.

When making any change, keep the Raspberry Pi target in mind: prefer low-CPU paths
(stream-copy over transcode), bounded memory, and graceful degradation.

---

## 1. General Style

- Follow **[PEP 8](https://peps.python.org/pep-0008/)** unless explicitly overridden below.
- **4 spaces** per indent level; **UTF-8** source files.
- Maximum line length: **120 characters**.
- One public class or function per file, where practical.
- Always use the project **`.venv`** for Python work (located at repo root: `.venv/`).
- If you find diagnostics / linter issues in code you touch, fix them immediately.
- Prefer clear, maintainable code over clever one-liners.

### 1.1 Web UI Versioning (cache busting)

Bump the version whenever you ship **any** user-visible change — not only edits inside
`backend/app/static/`. This includes backend/mobile dependency upgrades, bug fixes, and
behavior changes users would notice, even if no static file was touched directly. You
**MUST**:

1. Bump the version string in `index.html` (sidebar footer).
2. Bump the version in the `console.log` at the top of `main.js`.
3. Bump the `?v=X.X.X` query parameter on **every** `<script>` and `<link>` tag in
   `index.html` so browsers don't serve stale cached assets.

Also bump the version in `README.md` when shipping a user-visible change.

---

## 2. Imports

- Use **absolute imports** rooted at the `app` package (the backend runs with
  `pythonpath = .` from `backend/`).
- Place imports at the top of the file, grouped and blank-line separated:
  1. Standard library
  2. Third-party packages
  3. Local application (`app.*`)

```python
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.services import streamer
from app.utils.logger import setup_logger
```

### 2.1 `__init__.py` files

Keep all `__init__.py` files empty unless re-exporting is genuinely necessary.

### 2.2 UTC-aware dates

```python
# ❌ Do NOT
datetime.now(datetime.UTC)
# ✅ Do
from datetime import datetime, timezone
datetime.now(timezone.utc)
```

---

## 3. Logging

### 3.1 Initialization

Every module initializes its logger the same way:

```python
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)
```

### 3.2 Lazy formatting (always)

```python
# ❌ Do NOT
_logger.info(f"Processing track {track_id}")
# ✅ Do
_logger.info("Processing track %s", track_id)
```

### 3.3 Levels

- `debug()` – detailed debugging information.
- `info()` – high-level runtime events.
- `warning()` – unexpected but non-fatal events.
- `error()` – serious problems needing attention.
- `exception()` – like `error()` with stack trace; use **only inside `except`**.

### 3.4 Observability conventions

The streaming pipeline emits structured, greppable log lines (e.g.
`streamer: first byte path=... track=... elapsed_ms=...`,
`streamer: feeder stall ... gap_ms=...`, `yt_resolver: resolved video_id=... elapsed_ms=...`).
When adding hot-path code, follow this style: a stable prefix, `key=value` fields,
and millisecond timings. Never log secrets — the `SecretRedactFilter` is a safety net,
not an excuse.

---

## 4. Naming Conventions

- **Modules & packages**: `lowercase_with_underscores`
- **Classes**: `CamelCase`
- **Functions & variables**: `lowercase_with_underscores`
- **Constants**: `UPPERCASE_WITH_UNDERSCORES`
- **Private members**: prefix with `_`
- **Config settings**: `UPPERCASE_WITH_UNDERSCORES` on the `Settings` model in `app/config.py`.

---

## 5. Docstrings

- Follow **[PEP 257](https://peps.python.org/pep-0257/)**; triple double quotes.
- First line: short summary; blank line before any detailed description.

```python
def add(a: int, b: int) -> int:
    """
    Add two integers.

    Args:
        a: First integer.
        b: Second integer.

    Returns:
        The sum of `a` and `b`.
    """
    return a + b
```

---

## 6. Type Hints

- Type-hint all function arguments and return values.
- Use `Optional[...]` for nullable values; prefer precise types over `Any`.

```python
from typing import Optional

def greet(name: Optional[str] = None) -> str:
    return f"Hello, {name}!" if name else "Hello!"
```

---

## 7. Error Handling

- Never use a bare `except:`. Catch specific exceptions.
- A broad `except Exception` is acceptable only at defensive boundaries (background
  workers, network/subprocess pipelines) and must be paired with a `# pylint: disable`
  note or a logged reason — see `app/services/streamer.py` for the established pattern.
- Log exceptions with `_logger.exception("... %s", context)` inside the `except`.
- Raise meaningful HTTP errors (`HTTPException(status_code=..., detail=...)`) at the
  API layer; validate inputs early.

---

## 8. Code Structure

- Keep functions short and focused; prefer early returns over deep nesting.
- Extract helpers to avoid duplication.
- Keep blocking work (subprocess, sync I/O, `yt-dlp`) off the event loop — use
  `asyncio.to_thread(...)` or a worker thread, as the streamer does.

---

## 9. Backend Architecture (FastAPI)

The backend lives under `backend/app/`:

```
backend/
  run.py                 # local entrypoint (uvicorn)
  pytest.ini             # pythonpath=., asyncio_mode=auto, testpaths=app/tests
  requirements.txt
  alembic/               # DB migrations
  app/
    main.py              # FastAPI app + lifespan + middleware wiring
    config.py            # Settings (pydantic-settings); all tunables live here
    models.py            # SQLModel ORM models
    schemas.py           # Pydantic request/response schemas
    db.py                # engine / session
    dependencies.py      # shared FastAPI dependencies (auth, sessions)
    auth_utils.py        # JWT / signing helpers
    routers/             # one module per domain: tracks, auth, playlists, ai, system, ...
    services/            # business logic: streamer, yt_resolver, ytmusic, cache_manager, ...
    utils/               # cross-cutting helpers (logger, ...)
    middleware/          # request context, etc.
    static/              # Vanilla JS web player (api.js, player.js, main.js, ui.js, index.html)
    tests/               # pytest suite (test_*.py)
    docs/                # backend design docs (Design.md, Requirements.md)
```

Rules:

- **Routers** (`app/routers/`): thin; one router per domain, parse/validate and delegate.
- **Services** (`app/services/`): business logic shared across routers or non-trivial
  pipelines. New cross-cutting logic goes here, not in routers.
- **Dependencies** (`app/dependencies.py`): shared FastAPI `Depends(...)` providers.
- **Config** (`app/config.py`): add a typed setting with a sane default for every new
  tunable (env-overridable). Do not hard-code magic numbers in hot paths.
- **Lifespan**: use the FastAPI `lifespan` context manager for startup/shutdown — never
  the deprecated `@app.on_event`.
- **Migrations**: schema changes go through Alembic (`backend/alembic/`); never edit the
  SQLite file by hand.

---

## 10. Mobile (Flutter) Notes

- Code lives in `mobile/lib/` organized as `logic/` (BLoC), `models/`, `repositories/`,
  `services/`, `ui/`, `theme/`.
- Follow standard Dart/Flutter style (`flutter analyze` must pass — see
  `mobile/analysis_options.yaml`).
- Keep the mobile API client in sync with backend routes/schemas; the app reuses the
  signed stream-URL flow (`/tracks/stream/grant` → `/tracks/stream/{id}`).

---

## 11. Tests

- All new backend code must include unit tests under `backend/app/tests/`.
- Test function names: `test_<functionality>` (e.g. `test_prefetch_skips_when_disabled`).
- Run the suite from the `backend/` directory:

  ```bash
  cd backend
  ../.venv/Scripts/python.exe -m pytest -q        # Windows dev
  python -m pytest -q                             # Linux / CI / container
  ```

- `asyncio_mode = auto`, so `async def test_...` works without extra decorators.
- Tests must **not** hit the network or spawn `yt-dlp`/`ffmpeg`; mock those boundaries
  (the existing pipeline tests validate argv shape and pure helpers only).

### 11.1 Temporary / throwaway scripts

- Put one-off repro or debugging scripts in the session **scratchpad**, not in the repo.
- If a temporary script must live in the tree, place it under `backend/app/tests/` and
  prefix it with `tmp_` (e.g. `tmp_repro_stall.py`); never commit `tmp_*` files.
- ❌ Do **not** use the system `/tmp` directory.

---

## 12. Running & Deploying

- **Local backend**: from `backend/`, with `.venv` active, run `python run.py`
  (or `uvicorn app.main:app --reload`).
- **Container / Pi**: `docker compose up -d --build`. The `./backend/app` directory is
  bind-mounted, so most Python changes take effect on `docker compose restart backend`.
- **Logs** (Pi): `docker compose logs --since 10m backend` or the rotating file at
  `<MUSIC_HOST_ROOT>/db/app.log`.
- External binaries required at runtime: `ffmpeg`, `yt-dlp`, and `deno`/`node` for
  signature solving (the Docker image bundles Deno).

---

## 13. Git & Commit Messages

- Imperative mood: ✅ `"Add ranged-chunk feeder"`  ❌ `"Added ranged-chunk feeder"`.
- Reference issues when applicable: `"Fix #123 – handle 416 as clean EOF"`.
- Keep commits focused; don't mix a feature with unrelated reformatting.
- Commit or push only when asked; if on `main`, branch first.

---

## 14. AI Agent Guidelines (binding)

1. **Read this file** before generating or modifying code.
2. Apply **PEP 8** plus every custom rule above.
3. Use the standard **logger init** and **lazy logging** format.
4. **Always** include type hints and PEP 257 docstrings on new functions.
5. Use **absolute imports** from the `app` package; keep blocking work off the event loop.
6. Add a typed, env-overridable **config setting** (in `app/config.py`) for any new tunable.
7. Write **unit tests** for new backend functionality under `backend/app/tests/`; mock
   network/subprocess boundaries.
8. When touching `backend/app/static/`, follow the **Web UI Versioning** rules (§1.1).
9. Make **schema changes via Alembic**; never edit the SQLite DB directly.
10. Prefer **low-CPU, low-memory** designs — the production target is a Raspberry Pi 5.
11. Keep `README.md` and this file consistent when conventions or structure change.

---

*Last updated: 2026-06-28*
