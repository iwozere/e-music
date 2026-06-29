"""Standalone Edition launcher (docs/features-v7.md, Phases 3 & 6).

Starts the MySpotify backend in the ``standalone`` profile on the loopback interface and
shows the web UI in a native desktop window (pywebview), falling back to the default browser
when no window backend is available. No domain, tunnel, reverse proxy, or login is required —
the web UI auto-logs into the local single-user account.

Run it with::

    python -m app.desktop

Frontend selection (env overrides):
  MYSPOTIFY_NO_BROWSER=1   headless: run the server only, no window/browser (for automation)
  MYSPOTIFY_USE_BROWSER=1  force the default browser instead of the native window
  MYSPOTIFY_REMOTE=1       "Home Remote": bind 0.0.0.0, enable PIN pairing (POST /auth/pair),
                           and advertise on the LAN via mDNS so a phone can discover + connect
  MYSPOTIFY_PAIRING_PIN    optional fixed pairing PIN (otherwise a 6-digit one is generated)

This is the entrypoint that gets frozen into the desktop binary (PyInstaller).
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


def _bundled_ffmpeg():
    """Path to the ffmpeg shipped inside a frozen (PyInstaller) build, or None when running from source."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidate = os.path.join(base, "ffmpeg", exe)
    return candidate if os.path.isfile(candidate) else None


def _prepare_environment() -> None:
    """Force the standalone profile before ``app.config`` is imported (settings load at import)."""
    os.environ["APP_PROFILE"] = "standalone"
    for key in _SHADOW_ENV_KEYS:
        os.environ.setdefault(key, "")
    ffmpeg = _bundled_ffmpeg()
    if ffmpeg:
        os.environ.setdefault("FFMPEG_PATH", ffmpeg)


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


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _lan_ip() -> str:
    """Best-effort primary LAN IPv4 address (for the phone to connect to). Falls back to 127.0.0.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packets sent; just selects the outbound interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _load_or_create_pin(data_dir: str) -> str:
    """Return the LAN pairing PIN: env override, else a persisted 6-digit code (generated once)."""
    import secrets

    override = os.environ.get("MYSPOTIFY_PAIRING_PIN", "").strip()
    if override:
        return override
    pin_file = os.path.join(data_dir, "pair_pin") if data_dir else ""
    try:
        if pin_file and os.path.isfile(pin_file):
            existing = open(pin_file, encoding="utf-8").read().strip()
            if existing:
                return existing
        pin = f"{secrets.randbelow(1_000_000):06d}"
        if pin_file:
            with open(pin_file, "w", encoding="utf-8") as fh:
                fh.write(pin)
        return pin
    except OSError:
        return f"{secrets.randbelow(1_000_000):06d}"


def _advertise_mdns(port: int):
    """Advertise the service as ``_myspotify._tcp`` on the LAN so phones can discover it.

    Returns a (Zeroconf, ServiceInfo) pair to unregister later, or None if zeroconf is unavailable.
    """
    try:
        import socket as _socket

        from zeroconf import ServiceInfo, Zeroconf
    except Exception:
        return None
    try:
        ip = _lan_ip()
        info = ServiceInfo(
            "_myspotify._tcp.local.",
            f"MySpotify on {_socket.gethostname()}._myspotify._tcp.local.",
            addresses=[_socket.inet_aton(ip)],
            port=port,
            properties={"path": "/", "api": "/api/v1"},
            server=f"{_socket.gethostname()}.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        return (zc, info)
    except Exception as exc:
        print(f"[desktop] mDNS advertisement unavailable ({exc}).")
        return None


def _frontend_mode() -> str:
    """Choose how to present the UI: 'none' (headless), 'browser', or 'window' (default)."""
    if _env_flag("MYSPOTIFY_NO_BROWSER"):
        return "none"
    if _env_flag("MYSPOTIFY_USE_BROWSER"):
        return "browser"
    return "window"


def _run_window(url: str) -> bool:
    """Open the UI in a native pywebview window. Blocks until it's closed.

    Returns True if a window ran, False if no window backend is available (caller falls back).
    """
    try:
        import webview
    except Exception:
        return False
    try:
        webview.create_window(
            "MySpotify",
            url,
            width=1280,
            height=820,
            min_size=(940, 600),
        )
        webview.start()  # blocks on the main thread until the window is closed
        return True
    except Exception as exc:  # no GUI/WebView2 runtime, etc. — fall back to the browser
        print(f"[desktop] Native window unavailable ({exc}); using the browser instead.")
        return False


def main() -> int:
    _prepare_environment()
    preferred = int(os.environ.get("MYSPOTIFY_PORT", DEFAULT_PORT))
    port = _pick_port(preferred)

    # Import only after the environment is prepared so settings resolve in standalone mode.
    import uvicorn

    from app.config import settings

    # Prefer a self-updating yt-dlp from the data dir, before app.main imports yt_dlp.
    try:
        from app.standalone.ytdlp_updater import prepare_ytdlp
        prepare_ytdlp(settings.DATA_DIR)
    except Exception:
        pass

    # "Home Remote" (docs/features-v7.md §6): opt-in LAN access guarded by a pairing PIN.
    remote = _env_flag("MYSPOTIFY_REMOTE")
    bind_host = "0.0.0.0" if remote else "127.0.0.1"
    pin = ""
    if remote:
        pin = _load_or_create_pin(settings.DATA_DIR)
        settings.LOCAL_PAIRING_PIN = pin  # enables POST /auth/pair

    from app.main import app

    url = f"http://127.0.0.1:{port}"
    _write_runtime_file(settings.DATA_DIR, port)

    print("=" * 60)
    print("  MySpotify - Standalone Edition")
    print(f"  Profile : {settings.APP_PROFILE}  (auth: {settings.auth_mode()})")
    print(f"  Data    : {settings.DATA_DIR}")
    print(f"  Library : {settings.MUSIC_PATH}")
    print(f"  FFmpeg  : {settings.ffmpeg_executable()}{'  (bundled)' if _bundled_ffmpeg() else ''}")
    print(f"  URL     : {url}")
    if remote:
        print("-" * 60)
        print("  Home Remote ENABLED - connect your phone on the same Wi-Fi:")
        print(f"    Address : http://{_lan_ip()}:{port}")
        print(f"    PIN     : {pin}")
    print("=" * 60)

    config = uvicorn.Config(app, host=bind_host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if _wait_for_health(port):
        print(f"[desktop] Backend ready at {url}")
    else:
        print(f"[desktop] Backend not healthy yet - presenting {url} anyway.")

    mdns = _advertise_mdns(port) if remote else None
    if remote and mdns:
        print("[desktop] Discoverable on the LAN as '_myspotify._tcp'.")

    def _shutdown() -> None:
        print("\n[desktop] Shutting down...")
        if mdns:
            try:
                zc, info = mdns
                zc.unregister_service(info)
                zc.close()
            except Exception:
                pass
        server.should_exit = True
        thread.join(timeout=10)

    mode = _frontend_mode()
    if mode == "window":
        # Blocks until the window is closed; returns False if no window backend exists.
        if _run_window(url):
            _shutdown()
            return 0
        mode = "browser"  # fall through to browser + wait loop

    if mode == "browser":
        webbrowser.open(url)

    print("[desktop] Running. Press Ctrl+C to quit.")
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
