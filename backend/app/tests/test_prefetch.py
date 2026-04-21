"""Unit tests for ``streamer.prefetch_youtube`` status decisions and dedup.

We avoid spawning ffmpeg / yt-dlp by monkeypatching the resolver + the generator
builders. The service must still return the right ``PrefetchStatus`` string in
each branch.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Iterator, List

import pytest

from app.config import settings
from app.services import streamer
from app.services.streamer import PrefetchStatus
from app.services.yt_resolver import ResolvedFormat


@pytest.fixture(autouse=True)
def _isolate_streamer_state(monkeypatch, tmp_path):
    """Reset module-global state and redirect cache dirs to a temp folder."""
    temp_dir = tmp_path / "tmp_cache"
    persistent_dir = tmp_path / "persistent_cache"
    temp_dir.mkdir()
    persistent_dir.mkdir()
    monkeypatch.setattr(streamer, "TEMP_CACHE_DIR", str(temp_dir))
    monkeypatch.setattr(streamer, "PERSISTENT_CACHE_DIR", str(persistent_dir))

    with streamer._active_downloads_lock:  # noqa: SLF001
        streamer._active_downloads.clear()  # noqa: SLF001
    streamer._prefetch_semaphore = None  # noqa: SLF001

    # Always pretend ffmpeg is installed so the pre-flight doesn't short-circuit.
    monkeypatch.setattr(streamer.shutil, "which", lambda _name: "ffmpeg")
    yield
    with streamer._active_downloads_lock:  # noqa: SLF001
        streamer._active_downloads.clear()  # noqa: SLF001
    streamer._prefetch_semaphore = None  # noqa: SLF001


def _run(coro):
    return asyncio.run(coro)


def _make_resolved(video_id: str = "abc123") -> ResolvedFormat:
    return ResolvedFormat(
        video_id=video_id,
        url="https://example.test/stream",
        ext="m4a",
        acodec="mp4a.40.2",
        http_headers={},
        expires_at=time.monotonic() + 600,
    )


def test_prefetch_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "PREFETCH_ENABLED", False)
    result = _run(streamer.prefetch_youtube("abc12345"))
    assert result == PrefetchStatus.SKIPPED


def test_prefetch_returns_cached_when_file_exists(monkeypatch):
    monkeypatch.setattr(settings, "PREFETCH_ENABLED", True)

    # Drop a large enough "cached" file so validate_cache_file returns True.
    existing = Path(streamer.TEMP_CACHE_DIR) / "abc12345.webm"
    existing.write_bytes(b"\x00" * (200 * 1024))

    called = {"resolver": 0}

    async def _resolver(_vid, force_refresh=False):
        called["resolver"] += 1
        return _make_resolved("abc12345")

    monkeypatch.setattr(streamer, "resolver_resolve", _resolver)

    result = _run(streamer.prefetch_youtube("abc12345"))
    assert result == PrefetchStatus.CACHED
    # Cached short-circuit must run before we ever hit the resolver.
    assert called["resolver"] == 0


def test_prefetch_returns_in_progress_when_download_active(monkeypatch):
    monkeypatch.setattr(settings, "PREFETCH_ENABLED", True)
    # Pretend another request is already downloading this id.
    with streamer._active_downloads_lock:  # noqa: SLF001
        streamer._active_downloads["vid00001"] = threading.Event()  # noqa: SLF001

    result = _run(streamer.prefetch_youtube("vid00001"))
    assert result == PrefetchStatus.IN_PROGRESS


def test_prefetch_skipped_when_semaphore_full(monkeypatch):
    monkeypatch.setattr(settings, "PREFETCH_ENABLED", True)
    monkeypatch.setattr(settings, "PREFETCH_MAX_CONCURRENT", 1)

    sema = streamer._get_prefetch_semaphore()  # noqa: SLF001
    acquired = sema.acquire(blocking=False)
    assert acquired, "budget should have been free at test start"

    try:
        result = _run(streamer.prefetch_youtube("newtrack01"))
        assert result == PrefetchStatus.SKIPPED
    finally:
        sema.release()


def test_prefetch_started_spawns_worker_and_registers_download(monkeypatch):
    """When resolver + pipeline run, prefetch returns STARTED and a worker thread
    consumes the generator to completion, releasing _active_downloads at the end."""
    monkeypatch.setattr(settings, "PREFETCH_ENABLED", True)
    monkeypatch.setattr(settings, "PREFETCH_MAX_CONCURRENT", 2)
    monkeypatch.setattr(settings, "STREAM_FORCE_LEGACY_SUBPROCESS", False)

    async def _resolver(_vid, force_refresh=False):
        return _make_resolved("abcd1234")

    monkeypatch.setattr(streamer, "resolver_resolve", _resolver)

    gen_exhausted = threading.Event()

    def _fake_stream_resolved(*, track_id, resolved, download_path, final_path,
                              done_event, library_user_id):
        def gen() -> Iterator[bytes]:
            yield b"abc"
            yield b"def"
            gen_exhausted.set()
            # Mimic real generator cleanup so dedup registry clears.
            done_event.set()
            with streamer._active_downloads_lock:  # noqa: SLF001
                streamer._active_downloads.pop(track_id, None)  # noqa: SLF001
        return gen()

    monkeypatch.setattr(streamer, "_stream_resolved", _fake_stream_resolved)

    result = _run(streamer.prefetch_youtube("abcd1234"))
    assert result == PrefetchStatus.STARTED
    assert gen_exhausted.wait(timeout=2.0), "worker thread should have drained the generator"

    # Registry must clear after the worker completes.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with streamer._active_downloads_lock:  # noqa: SLF001
            if "abcd1234" not in streamer._active_downloads:  # noqa: SLF001
                break
        time.sleep(0.01)
    with streamer._active_downloads_lock:  # noqa: SLF001
        assert "abcd1234" not in streamer._active_downloads  # noqa: SLF001


def test_prefetch_uses_legacy_when_resolver_returns_none(monkeypatch):
    """No resolver + yt-dlp available → legacy worker is spawned."""
    monkeypatch.setattr(settings, "PREFETCH_ENABLED", True)
    monkeypatch.setattr(settings, "PREFETCH_MAX_CONCURRENT", 2)
    monkeypatch.setattr(settings, "STREAM_FORCE_LEGACY_SUBPROCESS", False)

    async def _resolver(_vid, force_refresh=False):
        return None

    monkeypatch.setattr(streamer, "resolver_resolve", _resolver)

    calls: List[str] = []

    def _fake_legacy(*, track_id, download_path, final_path, done_event, library_user_id):
        calls.append(track_id)

        def gen() -> Iterator[bytes]:
            yield b"x"
            done_event.set()
            with streamer._active_downloads_lock:  # noqa: SLF001
                streamer._active_downloads.pop(track_id, None)  # noqa: SLF001

        return gen()

    monkeypatch.setattr(streamer, "_stream_legacy_subprocess", _fake_legacy)

    result = _run(streamer.prefetch_youtube("legacyid1"))
    assert result == PrefetchStatus.STARTED
    # Give the worker a beat to actually enter the generator.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not calls:
        time.sleep(0.01)
    assert calls == ["legacyid1"]
