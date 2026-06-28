"""Standalone Edition launcher (docs/features-v7.md, Phase 3).

Starts the MySpotify backend in the ``standalone`` profile on the loopback interface and
opens the default browser. No domain, tunnel, reverse proxy, or login is required — the web
UI auto-logs into the local single-user account.

Run it with::

    python -m app.desktop

This is the entrypoint that later gets frozen into the desktop binary (PyInstaller). For now
it depends only on the project's existing requirements (uvicorn) plus the Python standard library.
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

DEFAULT_PORT = 8000

# Server-only settings that a repo/server ``.env`` might define. The standalone launcher
# shadows them so that file does not leak into the self-contained app. ``setdefault`` means a
# variable the user exported explicitly in their real shell still wins (e.g. to enable OAuth).
_SHADOW_ENV_KEYS = (
    "DATABASE_URL",
    "MUSIC_PATH",
    "CACHE_DIR",
    "TEMP_DIR",
    "JWT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
)


def _prepare_environment() -> None:
    """Force the standalone profile before ``app.config`` is imported (settings load at import)."""
    os.environ["APP_PROFILE"] = "standalone"
    for key in _SHADOW_ENV_KEYS:
        os.environ.setdefault(key, "")


def _pick_port(preferred: int = DEFAULT_PORT) -> int:
    """Return ``preferred`` if free, otherwise an OS-assigned ephemeral loopback port."""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Could not bind a local port on 127.0.0.1")


def _wait_for_health(port: int, timeout: float = 40.0) -> bool:
    """Poll ``/health`` until it returns 200 or ``timeout`` elapses."""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 (loopback only)
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _write_runtime_file(data_dir: str, port: int) -> None:
    """Record the live URL/port so a future desktop shell (or the user) can find it."""
    if not data_dir:
        return
    try:
        with open(os.path.join(data_dir, "runtime.json"), "w", encoding="utf-8") as fh:
            json.dump({"port": port, "url": f"http://127.0.0.1:{port}"}, fh)
    except OSError:
        pass


def _should_open_browser() -> bool:
    """Allow headless/automated runs to skip launching a browser (``MYSPOTIFY_NO_BROWSER=1``)."""
    return os.environ.get("MYSPOTIFY_NO_BROWSER", "").strip().lower() not in ("1", "true", "yes")


def main() -> int:
    _prepare_environment()
    preferred = int(os.environ.get("MYSPOTIFY_PORT", DEFAULT_PORT))
    port = _pick_port(preferred)

    # Import only after the environment is prepared so settings resolve in standalone mode.
    import uvicorn

    from app.config import settings
    from app.main import app

    url = f"http://127.0.0.1:{port}"
    _write_runtime_file(settings.DATA_DIR, port)

    print("=" * 60)
    print("  MySpotify - Standalone Edition")
    print(f"  Profile : {settings.APP_PROFILE}  (auth: {settings.auth_mode()})")
    print(f"  Data    : {settings.DATA_DIR}")
    print(f"  Library : {settings.MUSIC_PATH}")
    print(f"  URL     : {url}")
    print("=" * 60)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if _wait_for_health(port):
        print(f"[desktop] Backend ready at {url}")
    else:
        print(f"[desktop] Backend not healthy yet - opening {url} anyway.")

    if _should_open_browser():
        webbrowser.open(url)

    print("[desktop] Running. Press Ctrl+C to quit.")
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[desktop] Shutting down...")
        server.should_exit = True
        thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
